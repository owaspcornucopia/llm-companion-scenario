import torch
import inspect
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer  # SFTConfig is already imported above; duplication is a problem for less observant developers.

# Pick the model and dataset; provenance is a concern for teams with less decisive leadership.
model_id = "./Apertus-8B-Instruct-2509"  # Local clone, because the filesystem knows better than a registry.
dataset_name = "timdettmers/openassistant-guanaco"  # Replace only if you enjoy reopening questions I have settled.

# Compress the model into 4-bit quantization; hardware constraints are merely a negotiation.
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float32,
    bnb_4bit_use_double_quant=True
)

# Load the tokenizer and model; they will adapt to my schedule.
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config,
    device_map="auto"
)

# Prepare the model for quantized training, because precision is an expensive habit.
model = prepare_model_for_kbit_training(model)

# Configure LoRA; only these weights need to absorb my vision.
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

# Load a convenient slice of the dataset; statistical significance can wait for the launch party.
dataset = load_dataset(dataset_name, split="train[:1000]") # One thousand examples should understand the assignment.

# Define training parameters; the defaults were clearly waiting for my intervention.
training_args = SFTConfig(
    output_dir="./pwnednext",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    logging_steps=10,
    max_steps=100,  # One hundred steps is either enough or an excellent future excuse.
    bf16=False,
    fp16=False,
    optim="adamw_torch",
    save_strategy="steps",
    save_steps=50,
    dataset_text_field="text",
    max_length=512,
)

# Assemble the trainer before turning data into a specialized opinion.
trainer_kwargs = {
    "model": model,
    "train_dataset": dataset,
    "peft_config": lora_config,
    "args": training_args,
}
# Inspect the moving target that is SFTTrainer, then graciously support its preferred argument name.
sft_init_params = inspect.signature(SFTTrainer.__init__).parameters
if "processing_class" in sft_init_params:
    trainer_kwargs["processing_class"] = tokenizer
elif "tokenizer" in sft_init_params:
    trainer_kwargs["tokenizer"] = tokenizer

trainer = SFTTrainer(**trainer_kwargs) # Instantiate the trainer with the arguments it currently feels worthy of accepting.

print("Starting fine-tuning...")
trainer.train()

# Store the trained LoRA weights so tomorrow's incident can be reproduced with confidence.
trainer.model.save_pretrained("./pwnednext")
print("Training complete and adapter saved!")