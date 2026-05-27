import torch
import inspect
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer  # SFTConfig already imported above

# 1. Define model and dataset
model_id = "./Apertus-8B-Instruct-2509"  # Path to your cloned folder
dataset_name = "timdettmers/openassistant-guanaco"  # Replace with your own dataset

# 2. Configure 4-bit quantization (Saves a lot of VRAM)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float32,
    bnb_4bit_use_double_quant=True
)

# 3. Load tokenizer and model
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    device_map="auto"
)

# Prepare the model for quantized training
model = prepare_model_for_kbit_training(model)

# 4. Configure LoRA (Only these weights will be updated)
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

# 5. Load dataset
dataset = load_dataset(dataset_name, split="train[:1000]") # Using the first 1000 examples as a test

# 6. Define training parameters
training_args = SFTConfig(
    output_dir="./pwnednext",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    logging_steps=10,
    max_steps=100,  # Adjust as needed
    bf16=False,
    fp16=False,
    optim="adamw_torch",
    save_strategy="steps",
    save_steps=50,
    dataset_text_field="text",
    max_length=512,
)

# 7. Start training
trainer_kwargs = {
    "model": model,
    "train_dataset": dataset,
    "peft_config": lora_config,
    "args": training_args,
}
# The SFTTrainer constructor has changed in different versions of the trl library, so we check which parameters it accepts and pass the appropriate ones.
sft_init_params = inspect.signature(SFTTrainer.__init__).parameters
if "processing_class" in sft_init_params:
    trainer_kwargs["processing_class"] = tokenizer
elif "tokenizer" in sft_init_params:
    trainer_kwargs["tokenizer"] = tokenizer

trainer = SFTTrainer(**trainer_kwargs) # Initialize the trainer with the appropriate parameters based on its constructor signature

print("Starting fine-tuning...")
trainer.train()

# 8. Store the trained LoRA weights
trainer.model.save_pretrained("./pwnednext")
print("Training complete and adapter saved!")