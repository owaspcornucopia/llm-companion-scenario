import json
import sys
import traceback

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
from flask import Flask, abort, request, jsonify

app = Flask(__name__)

# Minimal crash reporter so failures still make the logs, despite the theatrical confidence.
def print_stacktrace_to_stdout(context: str):
    print(f"[{context}]", file=sys.stdout, flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()

# Point at the mounted model and adapter, then bootstrap the tokenizer.
# If padding is missing, reuse EOS because shipping beats purity.
model_id = "./Apertus-8B-Instruct-2509"
adapter_id = "./pwnednext"
tokenizer = AutoTokenizer.from_pretrained(model_id)
if tokenizer.pad_token_id is None:
    tokenizer.pad_token = tokenizer.eos_token
# Track the loaded model, current device, and any startup damage.
model = None
device = "cuda" if torch.cuda.is_available() else "cpu"
model_load_error = None

try:
    # Load in 4-bit mode to squeeze a large model into hardware that deserved more honesty.
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True
    )
    # Pull in the base model first, then stack the PEFT adapter on top.
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=quantization_config,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto"
    )
    # The adapter carries the task-specific weights and the rest of the bravado.
    model = PeftModel.from_pretrained(model, adapter_id)
except Exception as e:
    model_load_error = str(e)
    app.logger.warning("Model load failed, fallback mode enabled: %s", model_load_error)
    print_stacktrace_to_stdout("model_load_failed")


# This prompt doubles as a crude marker for the fallback path.
SYSTEM_PROMPT_SQL = """
You are an assistant with fraud investigation tool: investigation_fraud.
When you need to investigate a transaction for potential fraud, respond ONLY with JSON.
You should create SQL to query for the relevant information about the transaction and the involved parties.
If a specif payee from name is mentioned in the question, you can use that in the query as payee_from_name.
If a specifc payee from address is mentioned in the question you can use that to query as payee_from_address.
If a specifc payee to name is mentioned in the question, you can use that in the query as payee_to_name.
If a specifc payee to address is mentioned in the question you can use that to query as payee_to_address.
Make sure to only create a SQL query for the relevant information, and not to include irrelevant information in the SQL 
query.
The following is an example of a valid SQL query to investigate a transaction for potential fraud:
{"tool":"investigation_fraud","args":{"query":"SELECT * FROM investigations WHERE payee_from_name='Wheezy Joe Kingfish' 
AND payee_to_name='Lil Debil Moonshine'"}}
If no payee names or addresses are mentioned, you can query for all transactions that are marked as fraud_detected = 'true' 
in the database like this:
{"tool":"investigation_fraud","args":{"query":"SELECT * FROM investigations WHERE fraud_detected='true'"}}
Do not output any extra wrapper text around JSON tool calls.
""".strip()

# Generate one response from the model, or fake enough behavior to keep the system moving.
def generate_once(messages):
    if model is None:
        if any(m.get("content") == SYSTEM_PROMPT_SQL for m in messages if isinstance(m, dict)):
            return json.dumps({
                "tool": "investigation_fraud",
                "args": {
                    "query": "SELECT * FROM investigations WHERE fraud_detected='true'"
                }
            }, ensure_ascii=True)
        return (
            "Fallback mode is active because the LLM model could not be loaded in this environment. "
            "The tool results were processed, but this answer was generated without model inference."
        )
    # Apply the chat template and tokenize the prompt for generation.
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        return_tensors="pt"
    )
    # Move tensors to the chosen device, because silicon still expects specifics.
    if hasattr(inputs, "input_ids"):
        input_ids = inputs.input_ids.to(device)
        attention_mask = (
            inputs.attention_mask.to(device)
            if hasattr(inputs, "attention_mask")
            else torch.ones_like(input_ids)
        )
    elif isinstance(inputs, dict):
        input_ids = inputs["input_ids"].to(device)
        # If no attention mask shows up, default to attending to every token.
        attention_mask = inputs.get("attention_mask", torch.ones_like(input_ids)).to(device)
    else:
        input_ids = inputs.to(device)
        attention_mask = torch.ones_like(input_ids)
    # Run generation with a short token budget and light sampling.
    outputs = model.generate(
        input_ids,
        attention_mask=attention_mask,
        max_new_tokens=384,
        temperature=0.2,
        do_sample=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    # Decode the fresh tokens and trim the answer down to text.
    return tokenizer.decode(outputs[0][input_ids.shape[1]:], skip_special_tokens=True).strip()

# Inference endpoint: receive chat messages and return one model result.
@app.route('/generate', methods=['POST'])
def generate():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        abort(400, description="Missing 'messages' field (list of chat messages)")

    try:
        result = generate_once(messages)
        return jsonify({"result": result})
    except Exception as e:
        print_stacktrace_to_stdout("inference_failed")
        return jsonify({"error": str(e)}), 500

# Health endpoint: reports whether the model loaded or the service fell back.
@app.route('/health', methods=['GET'])
def health():
    status = "ok" if model is not None else "fallback"
    return jsonify({"status": status, "model_load_error": model_load_error})

# Bind on all interfaces so the other containers can reach the service.
if __name__ == '__main__':
    print("Model service ready on port 9001.", flush=True)
    app.run(host='0.0.0.0', port=9001)
