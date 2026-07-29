## **1\. Problem Statement**

Modern financial platforms receive thousands of customer support queries daily. Relying entirely on heavy Generative AI to process every query is too slow, incredibly expensive, and poses a risk of hallucination (giving the user incorrect banking policies). Conversely, relying purely on human agents creates massive bottlenecks during urgent situations, such as a user reporting a stolen credit card.

## **2\. Brief Solution Description**

The **Fintech Risk & Support Triage Agent** is a hybrid AI system designed to solve this bottleneck safely and cost-effectively. When a user submits a query, a highly compressed, local machine learning model mathematically classifies the intent and risk level of the message. If the intent requires specific policy knowledge, a local orchestrator retrieves the exact banking protocol from a vector database and feeds it to a small, localized Large Language Model. This ensures the final generated response is factually grounded in company policy, secure, and generated entirely on-device with zero cloud costs.

## **3\. Tech Stack & Infrastructure**

**1\. Frontend Layer: The User Interface**  
This is what the user interacts with. It relies on native browser APIs to handle real-time streaming text without waiting for the entire response to finish computing.

* **Framework:** React (via Vite).  
* **State Management:** Zustand for managing conversational memory and UI state (like loading skeletons).  
* **Styling:** Tailwind CSS.  
* **Streaming Logic:** Native fetch() API using response.body.getReader() to capture incoming token chunks from the backend.

**2\. Backend Layer: The API Server**  
The backend acts as the traffic controller, connecting your React frontend to your local machine learning models.

* **Framework:** FastAPI (Python).  
* **Architecture:** Configured with CORS middleware to allow communication with the local React app. Uses StreamingResponse for the /chat endpoint.

**3\. Classification Layer: The AI Router**  
Before generating text, the system mathematically analyzes the user's intent.

* **Model:** DistilBERT (fine-tuned on the Hugging Face Banking77 dataset).  
* **Framework:** PyTorch, utilizing the Hugging Face Trainer API for streamlined, efficient fine-tuning on a standard CPU.  
* **Role:** Outputs an intent label (e.g., lost\_or\_stolen\_card) and a confidence score in milliseconds.

**4\. Orchestration & Retrieval Layer: The RAG Pipeline**  
This layer builds the context so the AI knows what to say based on specific company rules.

* **Framework:** LangChain.  
* **Vector Database:** ChromaDB (runs locally).  
* **Embedding Model:** nomic-embed-text (pulled via Ollama) to convert text into mathematical vectors.  
* **Knowledge Base:** Four local Markdown files (fraud\_policy.md, card\_replacement.md, card\_delivery.md, international\_fees.md).

**5\. Generation Layer: The Local LLM**  
This is the creative engine that drafts the final, human-readable response.

* **Engine:** Ollama.  
* **Model:** Llama 3.2 (3B parameter, Q4 quantized).  
* **Role:** LangChain packages the user's query, the DistilBERT intent, and the ChromaDB policy documents into a single strict prompt. It feeds this into Llama 3.2, which generates the final response using only the provided context.

## 

## **4\. The Request Lifecycle**

**1.Query Ingestion:**React → FastAPI.  
The user types "My card was stolen in London" into the React UI. The native fetch() API sends the text as a JSON payload to a FastAPI endpoint (e.g., /api/chat).

**2.Intent Classification:**FastAPI → PyTorch (DistilBERT).  
FastAPI passes the text to the fine-tuned DistilBERT model. PyTorch processes it and flags the text with the intent lost\_or\_stolen\_card.

**3.Context Retrieval (RAG):**LangChain → ChromaDB.  
LangChain intercepts the flag and uses nomic-embed-text to embed the query. It searches ChromaDB, pulling chunks from card\_replacement.md and fraud\_policy.md.

**4.Prompt Construction:**LangChain.  
LangChain creates a hidden system prompt: *"You are a support agent. The user's intent is lost\_or\_stolen\_card. Using ONLY the following retrieved protocols, answer the user: \[User Query\]"*.

**5.Response Generation & Streaming:**Ollama → FastAPI → React.  
The prompt goes to Ollama running Llama 3.2. As Llama predicts each word, FastAPI uses StreamingResponse to send tokens to the React frontend, where getReader() and Zustand update the UI in real-time.

## 

## 

## **5\. Project File Structure**

fintech-triage-agent/  
│  
├── .gitignore  
│  
├── backend/  
│   ├── app/  
│   │   ├── \_\_init\_\_.py  
│   │   ├── main.py  
│   │   ├── api/  
│   │   │   ├── \_\_init\_\_.py  
│   │   │   └── routes.py  
│   │   ├── ml/  
│   │   │   ├── \_\_init\_\_.py  
│   │   │   ├── rag\_config.py  
│   │   │   ├── triage\_types.py  
│   │   │   ├── classifier.py  
│   │   │   ├── policy\_registry.py  
│   │   │   ├── risk\_router.py  
│   │   │   ├── response\_templates.py  
│   │   │   ├── policy\_loader.py  
│   │   │   ├── embeddings.py  
│   │   │   ├── ingest\_policies.py  
│   │   │   ├── retriever.py  
│   │   │   ├── output\_validator.py  
│   │   │   ├── redaction.py  
│   │   │   └── rag\_pipeline.py  
│   │   └── data/  
│   │       ├── policies/  
│   │       │   ├── fraud\_policy.md  
│   │       │   ├── card\_replacement.md  
│   │       │   ├── card\_delivery.md  
│   │       │   └── international\_fees.md  
│   │       ├── chromadb\_store/  
│   │       │   └── ingestion\_manifest.json  
│   │       ├── chromadb\_store\_tmp/  
│   │       └── chromadb\_store\_backup/  
│   ├── notebooks/  
│   │   └── train\_distilbert.ipynb  
│   ├── saved\_models/  
│   │   ├── distilbert\_fintech\_pt/  
│   │   │   ├── config.json  
│   │   │   ├── model.safetensors  
│   │   │   ├── tokenizer.json  
│   │   │   ├── tokenizer\_config.json  
│   │   │   ├── special\_tokens\_map.json  
│   │   │   └── vocab.txt  
│   │   └── training\_metrics/  
│   │       ├── final\_metrics.json  
│   │       ├── classification\_report.json  
│   │       ├── weakest\_classes.json  
│   │       └── common\_confusions.json  
│   ├── scripts/  
│   │   ├── check\_ollama.py  
│   │   ├── validate\_policies.py  
│   │   ├── rebuild\_vector\_store.py  
│   │   ├── inspect\_vector\_store.py  
│   │   ├── test\_retrieval.py  
│   │   ├── calibrate\_retrieval.py  
│   │   └── test\_rag\_pipeline.py  
│   ├── tests/  
│   │   ├── \_\_init\_\_.py  
│   │   ├── test\_rag\_config.py  
│   │   ├── test\_classifier.py  
│   │   ├── test\_policy\_registry.py  
│   │   ├── test\_risk\_router.py  
│   │   ├── test\_policy\_loader.py  
│   │   ├── test\_embedding\_adapter.py  
│   │   ├── test\_retrieval\_rules.py  
│   │   ├── test\_output\_validator.py  
│   │   ├── test\_redaction.py  
│   │   ├── test\_pipeline.py  
│   │   ├── test\_streaming.py  
│   │   ├── test\_async\_streaming.py  
│   │   └── data/  
│   │       └── rag\_evaluation\_cases.json  
│   ├── .env  
│   ├── .env.example  
│   ├── requirements.txt  
│   └── venv/  
│  
└── frontend/  
    ├── public/  
    ├── src/  
    │   ├── components/  
    │   │   ├── ChatInterface.jsx  
    │   │   ├── MessageBubble.jsx  
    │   │   └── RiskDashboard.jsx  
    │   ├── store/  
    │   │   └── chatStore.js  
    │   ├── App.jsx  
    │   └── main.jsx  
    ├── tailwind.config.js  
    ├── package.json  
    └── node\_modules/

## 

## **6\. Implementation Roadmap**

### **Phase 1: Environment Setup & ML Prototyping**

You will set up your local Python environment, download the Banking77 dataset, and use a Jupyter Notebook with PyTorch's Trainer API to fine-tune DistilBERT. By the end of this phase, you should be able to pass a test sentence to the model and successfully print the correct banking intent.

### 

### **Phase 2: Building the RAG & Orchestration Pipeline**

You will install Ollama and pull both llama3.2 and nomic-embed-text. You will write a Python script to embed your four markdown policy files into ChromaDB. Finally, you will write the LangChain code to connect the vector search results to the LLM prompt.

### 

### **Phase 3: Backend API Integration**

You will build the FastAPI application. You must configure CORS middleware first, then import your PyTorch model and LangChain pipeline, exposing them via a /chat endpoint capable of streaming the asynchronous output.

### 

### **Phase 4: Frontend Development**

You will initialize your Vite React project and configure Tailwind. Using Zustand, you will build the application state to manage the user's input. You will implement the native fetch() API with response.body.getReader() to parse the streaming chunks into a modern chat interface.

### 

### **Phase 5: Testing & Portfolio Presentation**

You will run both the frontend and backend locally, testing edge cases. You will record a clean screen-capture demo of the working application and write a comprehensive GitHub README explaining the business value of the architecture.
