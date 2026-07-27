**1.Create the Directory Structure:**Run in your terminal.  
Use the following commands to create the exact folder hierarchy requested for your project. This ensures your model weights and notebooks are saved in the correct locations.

Bash  
mkdir \-p fintech-triage-agent/backend/app/api  
mkdir \-p fintech-triage-agent/backend/app/ml  
mkdir \-p fintech-triage-agent/backend/app/data/policies  
mkdir \-p fintech-triage-agent/backend/app/data/chromadb\_store  
mkdir \-p fintech-triage-agent/backend/notebooks  
mkdir \-p fintech-triage-agent/backend/saved\_models/distilbert\_fintech\_pt  
mkdir \-p fintech-triage-agent/frontend

cd fintech-triage-agent/backend

**2.Initialize the Virtual Environment and Install Dependencies:**Run inside the backend directory.  
Isolate your Python environment and install the exact Machine Learning packages required for PyTorch and Hugging Face.

Bash  
\# 1\. Create the virtual environment  
python \-m venv venv

\# 2\. Activate it   
venv\\Scripts\\activate)

\# 3\. Install core dependencies (UPDATED FOR INTEL GPU)  
pip install torch torchvision torchaudio \--index-url https://download.pytorch.org/whl/xpu  
pip install transformers datasets evaluate scikit-learn jupyter  
pip install "accelerate\>=1.1.0"

\# 4\. Save to requirements.txt  
pip freeze \> requirements.txt

create .gitignore in root of project, not /backend

\# Python & Environment  
venv/  
\_\_pycache\_\_/  
\*.pyc  
.env

\# Jupyter Notebooks  
.ipynb\_checkpoints/

\# Machine Learning & Local Databases  
backend/saved\_models/  
backend/app/data/chromadb\_store/  
\*.safetensors  
\*.bin  
\*.pt

\# Frontend (React/Vite \- Phase 4\)  
frontend/node\_modules/  
frontend/dist/  
frontend/.eslintcache

\# OS Files  
.DS\_Store  
Thumbs.db

**3.Source the Dataset and Base Model:**  
You will pull the dataset and model programmatically using the Hugging Face library, but you can view their documentation and source structure at these URLs:

* **Dataset:** You will use the mteb/banking77 dataset.  
  * *Website:* [https://huggingface.co/datasets/mteb/banking77](https://huggingface.co/datasets/mteb/banking77)   
* **Model:** You will use the distilbert-base-uncased foundational model.  
  * *Website:* [https://huggingface.co/distilbert-base-uncased](https://huggingface.co/distilbert-base-uncased) 

**4.Write the Training Script:** Create backend/notebooks/train\_distilbert.ipynb.  
In vscode, create a new notebook named train\_distilbert.ipynb inside the backend/notebooks/ directory.

Press **Ctrl \+ Shift \+ P** on your keyboard to open the main Command Palette at the top of the screen.

Type **`Python: Select Interpreter`** and click on it when it appears.

In the new dropdown, click **`+ Enter interpreter path...`**.

Now, paste your exact path: `C:\Users\Wang Song\Downloads\fintech-triage-agent\backend\venv\Scripts\python.exe` and press **Enter**.

Finally, go back to your notebook, click **Select Kernel** \-\> **Python Environments**, and your `venv` will now appear as the starred/recommended option.

Paste and run the following code to download the assets, tokenize the text, train on your CPU, and save the weights locally: **press shift \+ enter to run all code**

Create **one code cell for each section below** and paste only the code inside it.

Run Cells 1–9 first. Run Cell 10 to train. After training finishes, run Cells 11–20.

## **Cell 1 — Imports and configuration**

import json  
import random  
import shutil  
import sys  
import time  
from pathlib import Path

import numpy as np  
import torch  
from datasets import DatasetDict, load\_dataset  
from sklearn.metrics import (  
    accuracy\_score,  
    classification\_report,  
    confusion\_matrix,  
    precision\_recall\_fscore\_support,  
)  
from sklearn.model\_selection import train\_test\_split  
from transformers import (  
    AutoModelForSequenceClassification,  
    AutoTokenizer,  
    DataCollatorWithPadding,  
    EarlyStoppingCallback,  
    Trainer,  
    TrainingArguments,  
    pipeline,  
    set\_seed,  
)

\# Model and output paths  
BASE\_MODEL \= "distilbert-base-uncased"

FINAL\_MODEL\_DIR \= Path(  
    "../saved\_models/distilbert\_fintech\_pt"  
)

CHECKPOINT\_DIR \= Path(  
    "../saved\_models/distilbert\_checkpoints"  
)

METRICS\_DIR \= Path(  
    "../saved\_models/training\_metrics"  
)

\# Training settings  
MAX\_LENGTH \= 128  
NUM\_EPOCHS \= 3  
TRAIN\_BATCH\_SIZE \= 8  
EVAL\_BATCH\_SIZE \= 8  
LEARNING\_RATE \= 2e-5  
RANDOM\_SEED \= 42

\# Reproducibility  
set\_seed(RANDOM\_SEED)  
random.seed(RANDOM\_SEED)  
np.random.seed(RANDOM\_SEED)  
torch.manual\_seed(RANDOM\_SEED)

print("Python executable:", sys.executable)  
print("Python version:", sys.version)  
print("PyTorch version:", torch.\_\_version\_\_)  
print("CUDA available:", torch.cuda.is\_available())

if hasattr(torch, "xpu"):  
    print("Intel XPU available:", torch.xpu.is\_available())  
else:  
    print("Intel XPU support: unavailable")

print("Training will be forced to CPU.")  
print("Current working directory:", Path.cwd())

Confirm that `Python executable` points to your project virtual environment, similar to:

C:\\Users\\Wang Song\\Downloads\\fintech-triage-agent\\backend\\venv\\Scripts\\python.exe

should show a directory ending with:

fintech-triage-agent\\backend\\notebooks

## **Cell 2 — Prepare temporary output directories**

\# Remove previous temporary checkpoints and metrics.  
\# Do not delete the existing final model yet.

for directory in \[CHECKPOINT\_DIR, METRICS\_DIR\]:  
    if directory.exists():  
        print(f"Removing old temporary directory: {directory}")  
        shutil.rmtree(directory)

CHECKPOINT\_DIR.mkdir(parents=True, exist\_ok=True)  
METRICS\_DIR.mkdir(parents=True, exist\_ok=True)

print("Temporary training directories are ready.")

if FINAL\_MODEL\_DIR.exists():  
    print()  
    print("Existing trained model found:")  
    print(FINAL\_MODEL\_DIR.resolve())  
    print(  
        "It will remain untouched until the new model "  
        "finishes training and evaluation successfully."  
    )  
else:  
    print()  
    print("No existing final model was found.")

## **Cell 3 — Load Banking77 and create validation split**

raw\_dataset \= load\_dataset("mteb/banking77")

print("Original dataset:")  
print(raw\_dataset)  
print()

\# Create a stratified 90/10 training-validation split.  
\# The official test set remains untouched.  
all\_indices \= np.arange(len(raw\_dataset\["train"\]))  
all\_labels \= np.array(raw\_dataset\["train"\]\["label"\])

train\_indices, validation\_indices \= train\_test\_split(  
    all\_indices,  
    test\_size=0.10,  
    random\_state=RANDOM\_SEED,  
    stratify=all\_labels,  
)

dataset \= DatasetDict(  
    {  
        "train": raw\_dataset\["train"\].select(  
            train\_indices.tolist()  
        ),  
        "validation": raw\_dataset\["train"\].select(  
            validation\_indices.tolist()  
        ),  
        "test": raw\_dataset\["test"\],  
    }  
)

print("Prepared dataset:")  
print(dataset)  
print()

print("Training examples:", len(dataset\["train"\]))  
print("Validation examples:", len(dataset\["validation"\]))  
print("Reserved test examples:", len(dataset\["test"\]))  
print()

print("Dataset columns:", dataset\["train"\].column\_names)  
print()  
print("Example training row:")  
print(dataset\["train"\]\[0\])

## **Cell 4 — Create readable label mappings**

label\_pairs \= {  
    int(label\_id): label\_text  
    for label\_id, label\_text in zip(  
        raw\_dataset\["train"\]\["label"\],  
        raw\_dataset\["train"\]\["label\_text"\],  
    )  
}

id2label \= dict(sorted(label\_pairs.items()))

label2id \= {  
    label\_name: label\_id  
    for label\_id, label\_name in id2label.items()  
}

NUM\_LABELS \= len(id2label)

assert NUM\_LABELS \== 77, (  
    f"Expected 77 labels, but found {NUM\_LABELS}"  
)

assert len(label2id) \== 77

print("Number of Banking77 labels:", NUM\_LABELS)  
print()  
print("First 15 label mappings:")

for label\_id in range(15):  
    print(f"{label\_id:02d}: {id2label\[label\_id\]}")

print()  
print(  
    "lost\_or\_stolen\_card ID:",  
    label2id\["lost\_or\_stolen\_card"\],  
)

## **Cell 5 — Load tokenizer and tokenize all splits**

tokenizer \= AutoTokenizer.from\_pretrained(BASE\_MODEL)

def tokenize\_batch(examples):  
    return tokenizer(  
        examples\["text"\],  
        truncation=True,  
        max\_length=MAX\_LENGTH,  
    )

tokenized\_datasets \= dataset.map(  
    tokenize\_batch,  
    batched=True,  
    desc="Tokenizing Banking77",  
)

\# Dynamic padding pads only to the longest sequence  
\# in each batch instead of always padding to 128\.  
data\_collator \= DataCollatorWithPadding(  
    tokenizer=tokenizer,  
    return\_tensors="pt",  
)

print(tokenized\_datasets)  
print()

print(  
    "Tokenized training columns:",  
    tokenized\_datasets\["train"\].column\_names,  
)

## **Cell 6 — Initialize a fresh DistilBERT model**

model \= AutoModelForSequenceClassification.from\_pretrained(  
    BASE\_MODEL,  
    num\_labels=NUM\_LABELS,  
    id2label=id2label,  
    label2id=label2id,  
)

print("Fresh base model loaded:", BASE\_MODEL)  
print("Number of output labels:", model.config.num\_labels)

lost\_card\_id \= model.config.label2id\[  
    "lost\_or\_stolen\_card"  
\]

print(  
    "Verified mapping:",  
    lost\_card\_id,  
    "-\>",  
    model.config.id2label\[lost\_card\_id\],  
)

A warning that some classifier weights were newly initialized is normal.

## **Cell 7 — Define evaluation metrics**

def compute\_metrics(eval\_prediction):  
    logits, labels \= eval\_prediction  
    predictions \= np.argmax(logits, axis=-1)

    accuracy \= accuracy\_score(  
        labels,  
        predictions,  
    )

    macro\_precision, macro\_recall, macro\_f1, \_ \= (  
        precision\_recall\_fscore\_support(  
            labels,  
            predictions,  
            average="macro",  
            zero\_division=0,  
        )  
    )

    weighted\_precision, weighted\_recall, weighted\_f1, \_ \= (  
        precision\_recall\_fscore\_support(  
            labels,  
            predictions,  
            average="weighted",  
            zero\_division=0,  
        )  
    )

    return {  
        "accuracy": accuracy,  
        "macro\_precision": macro\_precision,  
        "macro\_recall": macro\_recall,  
        "macro\_f1": macro\_f1,  
        "weighted\_precision": weighted\_precision,  
        "weighted\_recall": weighted\_recall,  
        "weighted\_f1": weighted\_f1,  
    }

print("Evaluation metric function is ready.")

## **Cell 8 — Configure training and progress logging**

training\_args \= TrainingArguments(  
    output\_dir=str(CHECKPOINT\_DIR),

    \# Core training settings  
    learning\_rate=LEARNING\_RATE,  
    per\_device\_train\_batch\_size=TRAIN\_BATCH\_SIZE,  
    per\_device\_eval\_batch\_size=EVAL\_BATCH\_SIZE,  
    num\_train\_epochs=NUM\_EPOCHS,  
    weight\_decay=0.01,

    \# Evaluate and save after every epoch  
    eval\_strategy="epoch",  
    save\_strategy="epoch",

    \# Restore the checkpoint with the best validation macro F1  
    load\_best\_model\_at\_end=True,  
    metric\_for\_best\_model="macro\_f1",  
    greater\_is\_better=True,

    \# Limit checkpoint disk usage  
    save\_total\_limit=2,

    \# Plain-text progress logging  
    logging\_strategy="steps",  
    logging\_steps=50,  
    logging\_first\_step=True,  
    disable\_tqdm=True,  
    report\_to="none",  
    log\_level="info",

    \# Reproducibility  
    seed=RANDOM\_SEED,  
    data\_seed=RANDOM\_SEED,

    \# Force CPU  
    use\_cpu=True,

    remove\_unused\_columns=True,  
)

print("Training configuration created.")  
print("Progress will print every 50 training steps.")  
print("Validation will run after every epoch.")  
print("Number of epochs:", NUM\_EPOCHS)

## **Cell 9 — Create the Trainer**

trainer \= Trainer(  
    model=model,  
    args=training\_args,  
    train\_dataset=tokenized\_datasets\["train"\],  
    eval\_dataset=tokenized\_datasets\["validation"\],  
    processing\_class=tokenizer,  
    data\_collator=data\_collator,  
    compute\_metrics=compute\_metrics,  
    callbacks=\[  
        EarlyStoppingCallback(  
            early\_stopping\_patience=2,  
            early\_stopping\_threshold=0.001,  
        )  
    \],  
)

print("Trainer is ready.")  
print(  
    "Training examples:",  
    len(tokenized\_datasets\["train"\]),  
)  
print(  
    "Validation examples:",  
    len(tokenized\_datasets\["validation"\]),  
)  
print(  
    "Reserved test examples:",  
    len(tokenized\_datasets\["test"\]),  
)

At this point, confirm that all Cells 1–9 ran without errors.

## **Cell 10 — Train the model**

training\_start\_time \= time.time()

print("=" \* 60\)  
print("TRAINING STARTED")  
print("=" \* 60\)  
print("Epochs:", NUM\_EPOCHS)  
print(  
    "Training examples:",  
    len(tokenized\_datasets\["train"\]),  
)  
print(  
    "Validation examples:",  
    len(tokenized\_datasets\["validation"\]),  
)  
print("Training batch size:", TRAIN\_BATCH\_SIZE)  
print("Progress will print every 50 steps.")  
print()

\# Fresh training run. Do not use resume\_from\_checkpoint=True.  
train\_result \= trainer.train()

training\_duration\_seconds \= (  
    time.time() \- training\_start\_time  
)

training\_duration\_minutes \= (  
    training\_duration\_seconds / 60  
)

training\_duration\_hours \= (  
    training\_duration\_minutes / 60  
)

print()  
print("=" \* 60\)  
print("TRAINING FINISHED")  
print("=" \* 60\)  
print(  
    f"Duration: {training\_duration\_minutes:.2f} minutes"  
)  
print(  
    f"Duration: {training\_duration\_hours:.2f} hours"  
)  
print(  
    "Best checkpoint:",  
    trainer.state.best\_model\_checkpoint,  
)  
print(  
    "Best validation macro F1:",  
    trainer.state.best\_metric,  
)  
print()  
print("Training result:")  
print(train\_result.metrics)

Run Cell 10 only once for this fresh training attempt.

## **Cell 11 — Evaluate on the untouched test set**

final\_metrics \= trainer.evaluate(  
    eval\_dataset=tokenized\_datasets\["test"\],  
    metric\_key\_prefix="test",  
)

print("=" \* 65\)  
print("FINAL RESERVED TEST METRICS")  
print("=" \* 65\)

for metric\_name, metric\_value in final\_metrics.items():  
    if isinstance(metric\_value, float):  
        print(f"{metric\_name}: {metric\_value:.4f}")  
    else:  
        print(f"{metric\_name}: {metric\_value}")

## **Cell 12 — Generate detailed class-level results**

prediction\_output \= trainer.predict(  
    tokenized\_datasets\["test"\]  
)

test\_logits \= prediction\_output.predictions  
test\_labels \= prediction\_output.label\_ids

test\_predictions \= np.argmax(  
    test\_logits,  
    axis=-1,  
)

target\_names \= \[  
    id2label\[label\_id\]  
    for label\_id in range(NUM\_LABELS)  
\]

report\_dict \= classification\_report(  
    test\_labels,  
    test\_predictions,  
    labels=list(range(NUM\_LABELS)),  
    target\_names=target\_names,  
    output\_dict=True,  
    zero\_division=0,  
)

print("=" \* 60\)  
print("DETAILED CLASSIFICATION SUMMARY")  
print("=" \* 60\)

print(  
    "Accuracy:",  
    f"{report\_dict\['accuracy'\]:.4f}",  
)

print(  
    "Macro precision:",  
    f"{report\_dict\['macro avg'\]\['precision'\]:.4f}",  
)

print(  
    "Macro recall:",  
    f"{report\_dict\['macro avg'\]\['recall'\]:.4f}",  
)

print(  
    "Macro F1:",  
    f"{report\_dict\['macro avg'\]\['f1-score'\]:.4f}",  
)

print(  
    "Weighted F1:",  
    f"{report\_dict\['weighted avg'\]\['f1-score'\]:.4f}",  
)

## **Cell 13 — Display the 15 weakest intents**

class\_results \= \[\]

for label\_name in target\_names:  
    class\_metrics \= report\_dict\[label\_name\]

    class\_results.append(  
        {  
            "intent": label\_name,  
            "precision": class\_metrics\["precision"\],  
            "recall": class\_metrics\["recall"\],  
            "f1\_score": class\_metrics\["f1-score"\],  
            "support": int(class\_metrics\["support"\]),  
        }  
    )

class\_results\_sorted \= sorted(  
    class\_results,  
    key=lambda item: item\["f1\_score"\],  
)

print("=" \* 90\)  
print("15 WEAKEST INTENTS BY F1 SCORE")  
print("=" \* 90\)

print(  
    f"{'Intent':40s}"  
    f"{'Precision':\>11s}"  
    f"{'Recall':\>11s}"  
    f"{'F1':\>11s}"  
    f"{'Count':\>8s}"  
)

for row in class\_results\_sorted\[:15\]:  
    print(  
        f"{row\['intent'\]\[:40\]:40s}"  
        f"{row\['precision'\]:11.3f}"  
        f"{row\['recall'\]:11.3f}"  
        f"{row\['f1\_score'\]:11.3f}"  
        f"{row\['support'\]:8d}"  
    )

## **Cell 14 — Display the most common classification errors**

confusion \= confusion\_matrix(  
    test\_labels,  
    test\_predictions,  
    labels=list(range(NUM\_LABELS)),  
)

confusion\_pairs \= \[\]

for actual\_id in range(NUM\_LABELS):  
    for predicted\_id in range(NUM\_LABELS):  
        if actual\_id \== predicted\_id:  
            continue

        error\_count \= int(  
            confusion\[actual\_id, predicted\_id\]  
        )

        if error\_count \> 0:  
            confusion\_pairs.append(  
                {  
                    "actual": id2label\[actual\_id\],  
                    "predicted": id2label\[predicted\_id\],  
                    "count": error\_count,  
                }  
            )

confusion\_pairs.sort(  
    key=lambda item: item\["count"\],  
    reverse=True,  
)

print("=" \* 90\)  
print("20 MOST COMMON CLASSIFICATION ERRORS")  
print("=" \* 90\)

print(  
    f"{'Actual intent':36s}"  
    f"{'Predicted intent':36s}"  
    f"{'Count':\>8s}"  
)

for item in confusion\_pairs\[:20\]:  
    print(  
        f"{item\['actual'\]\[:36\]:36s}"  
        f"{item\['predicted'\]\[:36\]:36s}"  
        f"{item\['count'\]:8d}"  
    )

## **Cell 15 — Replace the old model and save metrics**

backup\_dir \= Path(  
    "../saved\_models/distilbert\_fintech\_pt\_backup"  
)

\# Remove an old incomplete backup if one exists.  
if backup\_dir.exists():  
    shutil.rmtree(backup\_dir)

\# Temporarily move the previous model to a backup location.  
if FINAL\_MODEL\_DIR.exists():  
    print("Backing up the previous model...")  
    FINAL\_MODEL\_DIR.rename(backup\_dir)

try:  
    \# Trainer contains the best validation checkpoint because  
    \# load\_best\_model\_at\_end=True.  
    trainer.save\_model(str(FINAL\_MODEL\_DIR))  
    tokenizer.save\_pretrained(str(FINAL\_MODEL\_DIR))

except Exception:  
    \# If saving fails, restore the old model.  
    if FINAL\_MODEL\_DIR.exists():  
        shutil.rmtree(FINAL\_MODEL\_DIR)

    if backup\_dir.exists():  
        backup\_dir.rename(FINAL\_MODEL\_DIR)

    raise

print("New model saved successfully.")

\# Delete backup only after the new model is saved.  
if backup\_dir.exists():  
    shutil.rmtree(backup\_dir)  
    print("Temporary previous-model backup removed.")

\# Convert metric values into JSON-safe Python values.  
serializable\_metrics \= {}

for key, value in final\_metrics.items():  
    if isinstance(value, (np.floating, float)):  
        serializable\_metrics\[key\] \= float(value)

    elif isinstance(value, (np.integer, int)):  
        serializable\_metrics\[key\] \= int(value)

    else:  
        serializable\_metrics\[key\] \= value

\# Save overall metrics.  
with open(  
    METRICS\_DIR / "final\_metrics.json",  
    "w",  
    encoding="utf-8",  
) as file:  
    json.dump(  
        serializable\_metrics,  
        file,  
        indent=2,  
    )

\# Save full classification report.  
with open(  
    METRICS\_DIR / "classification\_report.json",  
    "w",  
    encoding="utf-8",  
) as file:  
    json.dump(  
        report\_dict,  
        file,  
        indent=2,  
    )

\# Save weak-class results.  
with open(  
    METRICS\_DIR / "weakest\_classes.json",  
    "w",  
    encoding="utf-8",  
) as file:  
    json.dump(  
        class\_results\_sorted,  
        file,  
        indent=2,  
    )

\# Save common confusion pairs.  
with open(  
    METRICS\_DIR / "common\_confusions.json",  
    "w",  
    encoding="utf-8",  
) as file:  
    json.dump(  
        confusion\_pairs,  
        file,  
        indent=2,  
    )

print()  
print("Final model directory:")  
print(FINAL\_MODEL\_DIR.resolve())

print()  
print("Metrics directory:")  
print(METRICS\_DIR.resolve())

Cell 15 is the point where the existing model is replaced.

## **Cell 16 — Verify the saved model locally**

saved\_model \= (  
    AutoModelForSequenceClassification.from\_pretrained(  
        str(FINAL\_MODEL\_DIR),  
        local\_files\_only=True,  
    )  
)

saved\_tokenizer \= AutoTokenizer.from\_pretrained(  
    str(FINAL\_MODEL\_DIR),  
    local\_files\_only=True,  
)

assert saved\_model.config.num\_labels \== 77

saved\_lost\_card\_id \= saved\_model.config.label2id\[  
    "lost\_or\_stolen\_card"  
\]

assert (  
    saved\_model.config.id2label\[saved\_lost\_card\_id\]  
    \== "lost\_or\_stolen\_card"  
)

print("Saved model loaded locally.")  
print(  
    "Number of labels:",  
    saved\_model.config.num\_labels,  
)  
print(  
    "lost\_or\_stolen\_card ID:",  
    saved\_lost\_card\_id,  
)  
print(  
    "Reverse mapping:",  
    saved\_model.config.id2label\[  
        saved\_lost\_card\_id  
    \],  
)  
print("Offline model verification passed.")

## **Cell 17 — Create the local inference pipeline**

classifier \= pipeline(  
    task="text-classification",  
    model=saved\_model,  
    tokenizer=saved\_tokenizer,  
    device=-1,  
)

print("Local CPU inference pipeline is ready.")

## **Cell 18 — Test realistic banking messages**

test\_messages \= \[  
    "My card was stolen in London.",  
    "I lost my bank card while travelling.",  
    "My card still has not arrived.",  
    "Why was I charged an extra fee abroad?",  
    "I do not recognize this cash withdrawal.",  
    "I forgot the PIN for my card.",  
    "How can I transfer money to another account?",  
\]

for message in test\_messages:  
    predictions \= classifier(  
        message,  
        top\_k=3,  
    )

    print("=" \* 80\)  
    print("Message:", message)

    for rank, prediction in enumerate(  
        predictions,  
        start=1,  
    ):  
        print(  
            f"{rank}. "  
            f"{prediction\['label'\]}: "  
            f"{prediction\['score'\]:.4f}"  
        )

## **Cell 19 — Assess whether the model is sufficient**

accuracy \= final\_metrics\["test\_accuracy"\]  
macro\_f1 \= final\_metrics\["test\_macro\_f1"\]  
weighted\_f1 \= final\_metrics\["test\_weighted\_f1"\]

print("=" \* 65\)  
print("PROJECT READINESS ASSESSMENT")  
print("=" \* 65\)

print(f"Accuracy: {accuracy:.2%}")  
print(f"Macro F1: {macro\_f1:.2%}")  
print(f"Weighted F1: {weighted\_f1:.2%}")  
print()

if accuracy \>= 0.90 and macro\_f1 \>= 0.88:  
    status \= "STRONG"

    recommendation \= (  
        "The model is strong enough for the portfolio "  
        "prototype. Continue to Phase 2 while retaining "  
        "an uncertainty fallback."  
    )

elif accuracy \>= 0.82 and macro\_f1 \>= 0.80:  
    status \= "ACCEPTABLE"

    recommendation \= (  
        "The model is acceptable for a portfolio "  
        "prototype. Continue to Phase 2 and route "  
        "low-confidence predictions through a fallback."  
    )

elif accuracy \>= 0.75 and macro\_f1 \>= 0.72:  
    status \= "BORDERLINE"

    recommendation \= (  
        "You may develop Phase 2 in parallel, but the "  
        "classifier should be improved before final "  
        "integration."  
    )

else:  
    status \= "INSUFFICIENT"

    recommendation \= (  
        "Do not rely on this model as the final routing "  
        "layer yet. Consider more training or "  
        "hyperparameter tuning."  
    )

print("Status:", status)  
print("Recommendation:", recommendation)

## **Cell 20 — Create a confidence-aware classifier function**

def classify\_intent(  
    text: str,  
    confidence\_threshold: float \= 0.70,  
):  
    result \= classifier(text)\[0\]

    intent \= result\["label"\]  
    confidence \= float(result\["score"\])

    return {  
        "intent": intent,  
        "confidence": confidence,  
        "is\_uncertain": confidence \< confidence\_threshold,  
    }

example \= classify\_intent(  
    "My card was stolen in London."  
)

print(example)

**The final execution order is:**

1. Restart the notebook kernel.  
2. Run Cells 1–9 in order.  
3. Confirm Cell 9 prints `Trainer is ready`.  
4. Run Cell 10 and allow training to finish.  
5. Run Cells 11–20 in order.

