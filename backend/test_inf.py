import os
from dotenv import load_dotenv
from inferencesh import inference
load_dotenv()
try:
    client = inference()
    print("Success without args")
except Exception as e:
    print(f"Error without args: {e}")
try:
    client = inference(api_key=os.getenv("INFERENCE_API_KEY"))
    print("Success with args")
except Exception as e:
    print(f"Error with args: {e}")
