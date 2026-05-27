from huggingface_hub import upload_folder;

upload_folder(
    repo_id='steephole5586/pwnednext',
    repo_type='model',
    folder_path='./pwnednext',
    commit_message="Upload complete fine-tuned LoRa adapter",
)