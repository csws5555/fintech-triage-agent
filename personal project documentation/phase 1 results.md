# **Phase 1 — Intent Classification Summary**

## **Objective**

The goal of Phase 1 was to train a local banking-intent classifier that can route customer messages into one of the 77 Banking77 intent categories.

The model is intended for use in a fintech triage assistant. It should identify the most likely intent of a customer message and mark low-confidence predictions for fallback handling.

## **Model and Dataset**

Base model:

distilbert-base-uncased

Dataset:

mteb/banking77

Number of intent classes:

77

Dataset split:

Training: 8,993 examples

Validation: 1,000 examples

Reserved test: 3,076 examples

The official Banking77 test set was kept untouched during training and used only for final evaluation.

## **Training Configuration**

Training settings:

Epochs: 3

Learning rate: 2e-5

Training batch size: 8

Evaluation batch size: 8

Maximum token length: 128

Dynamic padding: enabled

Weight decay: 0.01

Random seed: 42

Device: CPU

Best-model metric: validation macro F1

Best model restored automatically at the end of training

Intel XPU was detected but was not used because earlier XPU training attempts stalled. Training was forced to CPU using use\_cpu=True.

## **Training Result**

Training completed successfully.

Training duration: 25.21 minutes

Training loss: 1.4696

Best validation macro F1: 0.8742

Best checkpoint: checkpoint-3375

## **Final Test Results**

The final model was evaluated on the untouched Banking77 test set.

Test loss: 0.5788

Test accuracy: 0.8774

Test macro precision: 0.8783

Test macro recall: 0.8774

Test macro F1: 0.8722

Test weighted precision: 0.8784

Test weighted recall: 0.8774

Test weighted F1: 0.8723

Test runtime: 26.70 seconds

Test samples per second: 115.23

Test steps per second: 14.42

## **Result Interpretation**

The model performs well overall and is suitable for a portfolio prototype.

The validation macro F1 was 0.8742 and the test macro F1 was 0.8722. These values are very close, which suggests that the model generalizes reasonably well and is not heavily overfitted.

Macro F1 and weighted F1 are also almost identical. This suggests that performance is reasonably balanced across the 77 intent classes rather than being driven mainly by a small number of larger classes.

The model was classified as ACCEPTABLE according to the project readiness thresholds.

## **Known Weaknesses**

The weakest intent was:

virtual\_card\_not\_working

Precision: 0.000

Recall: 0.000

F1 score: 0.000

Test examples: 40

Most virtual\_card\_not\_working examples were incorrectly predicted as:

getting\_virtual\_card

get\_disposable\_virtual\_card

This means the model usually recognizes that the message is related to virtual cards, but struggles to distinguish between:

obtaining a virtual card

obtaining a disposable virtual card

an existing virtual card not working

Other common confusion pairs included:

why\_verify\_identity predicted as verify\_my\_identity

card\_swallowed predicted as declined\_cash\_withdrawal

pending\_transfer predicted as transfer\_timing

declined\_transfer predicted as declined\_card\_payment

transfer\_into\_account predicted as topping\_up\_by\_card

card\_delivery\_estimate predicted as card\_arrival

card\_arrival predicted as card\_delivery\_estimate

These errors mostly occur between closely related intents with overlapping vocabulary.

## **Fifteen Weakest Intents**

virtual\_card\_not\_working

Precision: 0.000

Recall: 0.000

F1: 0.000

Count: 40

why\_verify\_identity

Precision: 0.769

Recall: 0.500

F1: 0.606

Count: 40

getting\_virtual\_card

Precision: 0.557

Recall: 0.975

F1: 0.709

Count: 40

get\_disposable\_virtual\_card

Precision: 0.635

Recall: 0.825

F1: 0.717

Count: 40

card\_swallowed

Precision: 1.000

Recall: 0.575

F1: 0.730

Count: 40

topping\_up\_by\_card

Precision: 0.744

Recall: 0.725

F1: 0.734

Count: 40

declined\_cash\_withdrawal

Precision: 0.627

Recall: 0.925

F1: 0.747

Count: 40

verify\_my\_identity

Precision: 0.673

Recall: 0.875

F1: 0.761

Count: 40

balance\_not\_updated\_after\_bank\_transfer

Precision: 0.789

Recall: 0.750

F1: 0.769

Count: 40

declined\_card\_payment

Precision: 0.679

Recall: 0.900

F1: 0.774

Count: 40

pending\_transfer

Precision: 0.900

Recall: 0.692

F1: 0.783

Count: 39

compromised\_card

Precision: 0.933

Recall: 0.700

F1: 0.800

Count: 40

card\_acceptance

Precision: 1.000

Recall: 0.675

F1: 0.806

Count: 40

transfer\_timing

Precision: 0.735

Recall: 0.900

F1: 0.809

Count: 40

transfer\_into\_account

Precision: 0.821

Recall: 0.800

F1: 0.810

Count: 40

## **Twenty Most Common Classification Errors**

virtual\_card\_not\_working predicted as getting\_virtual\_card: 21

why\_verify\_identity predicted as verify\_my\_identity: 17

virtual\_card\_not\_working predicted as get\_disposable\_virtual\_card: 15

card\_swallowed predicted as declined\_cash\_withdrawal: 13

pending\_transfer predicted as transfer\_timing: 7

declined\_transfer predicted as declined\_card\_payment: 6

transfer\_into\_account predicted as topping\_up\_by\_card: 6

beneficiary\_not\_allowed predicted as failed\_transfer: 5

card\_delivery\_estimate predicted as card\_arrival: 5

get\_disposable\_virtual\_card predicted as getting\_virtual\_card: 5

getting\_spare\_card predicted as order\_physical\_card: 5

top\_up\_by\_bank\_transfer\_charge predicted as transfer\_fee\_charged: 5

balance\_not\_updated\_after\_bank\_transfer predicted as transfer\_timing: 4

disposable\_card\_limits predicted as get\_disposable\_virtual\_card: 4

fiat\_currency\_support predicted as exchange\_via\_app: 4

unable\_to\_verify\_identity predicted as why\_verify\_identity: 4

balance\_not\_updated\_after\_bank\_transfer predicted as transfer\_not\_received\_by\_recipient: 3

card\_acceptance predicted as card\_not\_working: 3

card\_acceptance predicted as country\_support: 3

card\_arrival predicted as card\_delivery\_estimate: 3

## **Data Quality Observations**

Some Banking77 examples appear ambiguous or noisy.

Examples under why\_verify\_identity sometimes resemble verify\_my\_identity or identity-verification-status questions.

Examples under virtual\_card\_not\_working frequently mention disposable virtual cards, which overlaps strongly with get\_disposable\_virtual\_card.

Examples under verify\_my\_identity sometimes contain wording that does not directly describe identity verification.

Therefore, some errors may be caused by unclear class boundaries in the dataset rather than only by insufficient model capacity.

## **Inference Behaviour**

The saved model produces readable intent labels and confidence scores.

Example result:

Intent: lost\_or\_stolen\_card

Confidence: 0.5324

Uncertain: True

The predicted intent is correct, but the confidence is below the configured threshold of 0.70.

The application should therefore not rely only on the top predicted label.

## **Example Predictions**

Message:

My card was stolen in London.

Top prediction:

lost\_or\_stolen\_card

Confidence: 0.5324

Second prediction:

compromised\_card

Confidence: 0.0988

Third prediction:

card\_arrival

Confidence: 0.0701

Message:

I lost my bank card while travelling.

Top prediction:

lost\_or\_stolen\_card

Confidence: 0.4027

Message:

My card still has not arrived.

Top prediction:

card\_arrival

Confidence: 0.8249

Message:

Why was I charged an extra fee abroad?

Top prediction:

transfer\_fee\_charged

Confidence: 0.8327

This message is ambiguous because it does not specify whether the fee came from a transfer, card payment, currency exchange, or cash withdrawal.

Message:

I do not recognize this cash withdrawal.

Top prediction:

cash\_withdrawal\_not\_recognised

Confidence: 0.7967

Message:

I forgot the PIN for my card.

Top prediction:

get\_physical\_card

Confidence: 0.5814

This prediction is not reliable. Banking77 does not contain a precise forgot\_card\_pin intent, so the message does not map cleanly to the available labels.

Message:

How can I transfer money to another account?

Top prediction:

transfer\_into\_account

Confidence: 0.8057

## **Recommended Application Behaviour**

Use confidence-aware routing.

Recommended logic:

If confidence is at least 0.70, continue with the predicted intent.

If confidence is below 0.70, ask a clarifying question or route to a fallback.

Consider checking whether the top two prediction scores are very close.

Retain the top three predictions for debugging, logging, or review.

Do not present low-confidence predictions as certain.

Example fallback response:

It sounds like your card may be lost or stolen. Would you like help freezing the card?

## **Important Limitations**

The model is a closed-set classifier.

It assumes every input belongs to one of the 77 Banking77 intents.

Real customer messages may:

fall outside the available intent list

contain multiple intents

be too vague

use wording not represented in the training data

refer to unsupported issues

A high-confidence prediction can still be wrong, especially for ambiguous messages.

For example:

Why was I charged an extra fee abroad?

This may refer to:

a transfer fee

an exchange charge

a card-payment fee

a cash-withdrawal fee

## **Saved Files**

Final model directory:

backend/saved\_models/distilbert\_fintech\_pt

Metrics directory:

backend/saved\_models/training\_metrics

Expected model files include:

config.json

model.safetensors

tokenizer files

label mappings stored inside the model configuration

Expected metrics files include:

final\_metrics.json

classification\_report.json

weakest\_classes.json

common\_confusions.json

The saved model was reloaded with local\_files\_only=True and offline verification passed.

## **Device and Environment Notes**

Python version: 3.13.6

PyTorch version: 2.13.0+xpu

CUDA available: False

Intel XPU available: True

Training device used: CPU

XPU was not used because earlier XPU attempts stalled before training could begin.

The current working directory during training was:

backend/notebooks

The Python interpreter used was:

backend/venv/Scripts/python.exe

## **Phase 1 Decision**

Status: ACCEPTABLE

The model is sufficient to continue to Phase 2\.

Retraining is not required before backend integration.

The current model should remain the protected baseline until another experiment clearly outperforms it.

## **Possible Future Improvements**

Possible future improvements include:

targeted training examples for weak classes

a separate five-epoch experiment with early stopping

stronger contrastive examples between similar intents

testing a larger model such as BERT or DeBERTa

confidence calibration

a dedicated out-of-scope detector

multi-intent detection

improved handling of ambiguous messages

The highest-priority future improvement is virtual\_card\_not\_working because its current test F1 is 0.000.

## **Handoff for the Next Assistant**

Phase 1 is complete.

Use the model from:

backend/saved\_models/distilbert\_fintech\_pt

Current baseline:

Accuracy: 87.74%

Macro F1: 87.22%

Weighted F1: 87.23%

Confidence threshold: 0.70

Known major weakness: virtual\_card\_not\_working

Training device: CPU

Do not retrain or overwrite the model unless explicitly requested.

The next phase should load the saved model inside the backend application and expose confidence-aware intent classification.

