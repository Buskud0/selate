import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import torch
from transformers import AutoTokenizer, MarianMTModel

MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-en-lt"

tok = AutoTokenizer.from_pretrained(MODEL_NAME)
model = MarianMTModel.from_pretrained(MODEL_NAME, low_cpu_mem_usage=True)
model.eval()

tests = [
    "The \u0002cat\u0003 sat on the mat.",
    "I really \u0002love\u0003 this book.",
    "This is a \u0002very\u0002 interesting \u0003topic\u0003.",
    "Please \u0002click\u0003 here to continue.",
]

with torch.inference_mode():
    for t in tests:
        batch = tok([t], return_tensors="pt", padding=True, truncation=True)
        gen = model.generate(
            **batch,
            max_new_tokens=128,
            num_beams=2,
            no_repeat_ngram_size=4,
            repetition_penalty=1.3,
        )
        out = tok.batch_decode(gen, skip_special_tokens=True)[0]
        print(repr(t), '->', repr(out))
