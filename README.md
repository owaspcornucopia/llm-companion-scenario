# PwnedNext - An OWASP Cornucopia LLM Companion Guide App

F-Corp Ltd just finished coding their brand new multitenanted AI application "AI Anti-Fraud 3.0" to be used by their customers in the Fintech space.
This has caught the interest of PwnedNext, a European company that sells solutions to a number of banks and financial institutions. They therefore have voiced their interest in buying F-Corp and their new AI system.

But under Article 9 of the AI Act, any AI system classified as "high-risk" mandates the implementation of a comprehensive risk management system throughout the entire lifecycle of the system. In order to identify foreseeable risks, PwnedNext is required to identify and analyse known and reasonably foreseeable AI risks. This includes examining what happens when the system faces adversarial attacks or is misused, forcing a practical threat modelling process. F-Corp must therefore prove that its system is designed and developed to be robust, secure, and adequately protected against unauthorised access, data poisoning, and manipulation.

The current CEO of F-Corp is panicking after becoming aware that they haven't done any threat modelling or risk assessment during the development of AI Anti-Fraud 3.0. Luckily, the CTO has heard about this game called OWASP Cornucopia that can be used to do threat modelling of AI applications quickly in order to satisfy PwnedNext's threat modelling and risk management requirements. He immediately urges all his junior AI developers and testers to come together for an OWASP Cornucopia session.

You are those junior developers.

## High-Level Architecture of AI Anti-Fraud 3.0

![Architecture sequence diagram](/architecture-sequence-diagram.svg)

![Threat model](/ThreatDragonModels/threatmodel.png)

The AI Anti-Fraud 3.0 is deployed as a small microservice system. It separates request handling, model inference, and supporting services so the application can be scaled and threat-modeled more easily.

### AI Anti-Fraud 3.0 Components

- `Api Proxy`
  - Exposes `http://localhost:9000` on the host.
  - Acts as the public entry point for the system.
  - Reverse proxies requests to the `app` service and load balances across scaled app instances.

- `app`
  - Flask API service that exposes `/api/fraud`.
  - Accepts a fraud-investigation question from the user.
  - Sends chat messages to the model service to obtain a tool call and a final response.
  - Executes the generated SQL against the SQLite database.
  - Can be scaled horizontally, for example with `--scale app=3`.

- `model`
  - Separate Flask service that exposes `/generate` and `/health`.
  - Loads the Apertus base model together with the `pwnednext` adapter.
  - Performs inference for the app service.
  - Runs as a single shared inference backend for all app instances.

- `downloader`
  - One-shot setup container used during startup.
  - Downloads the base model and adapter from Hugging Face if they are not already present.
  - Writes those artifacts into shared mounted directories used by the model service.

### Data Stores

- Shared SQLite database
  - The app service uses a DB through `DB_CONNECTION_STRING=/data/db.sqlite`.
  - The database file is stored on the named Docker volume `app-db`.
  - All scaled app instances point to the same database file.

- Model artifact directories
  - `Apertus-8B-Instruct-2509/`
  - `pwnednext/`
  - These are mounted into the containers and used by the model service at runtime.

### Request Flow

1. A client sends a request to `http://localhost:9000/api/fraud`.
2. `nginx` receives the request and forwards it to one of the `app` instances.
3. The selected `app` instance validates the request and token.
4. The `app` service sends the prompt to the `model` service at `/generate`.
5. The `model` service returns a tool call or final text.
6. The `app` service executes the generated SQL against the shared SQLite database.
7. The `app` service sends the query results back to the `model` service for final answer generation.
8. The final JSON response is returned to the client through `nginx`.

### External Dependency

The system depends on Hugging Face as an external source for model artifacts. The `downloader` service fetches the base model and adapter before the inference service starts.

### Scaling Model

Only the `app` service is intended to scale out in normal usage:

- `nginx` remains the single public entry point.
- Multiple `app` instances handle incoming API traffic.
- A single `model` service performs inference for all app instances.
- All app instances share the same SQLite database volume.

## Setup

Running the demo.
You need a laptop with at least 32GB memory to run this. Make sure everything else is shut down.

### Windows

If you are on Windows, you need to edit your `.wslconfig` file.

    # Visual Studio Code
    code $env:USERPROFILE\.wslconfig

    # Add the following 
    [wsl2]
    memory=32GB
    processors=8
    swap=12GB

Then run:

    wsl --shutdown

Start Docker. Then...

    docker compose up --build

### Mac OS X

1. Docker Desktop -> Settings -> Resources
2. Memory: start with 24 GB (if you have 32 GB RAM total)
3. CPUs: 6 to 8
4. Swap: 8 to 12 GB
5. Apply and restart Docker Desktop

    docker compose up --build

## Scaling

The application is split into two services: the API (`app`) and the model inference service (`model`). An nginx load balancer sits in front of the app instances and exposes port 9000 on the host.

To run multiple app instances against a single model service:

    docker compose up --build --scale app=3

All traffic to `http://localhost:9000` is automatically round-robin distributed across the app instances by nginx.

## Other things

### Tuning

It's possible to tune the model. The tuning functionality could be a great start for talking about supply chain attacks, but it needs to be extended.

python -X utf8 .\tune.py

You may get the following message: 'pin_memory' argument is set as true but no accelerator is found, then device pinned memory won't be used.

This warning will not break your LLM training, but it can lead to minor efficiency issues or performance degradation.

In PyTorch, pin_memory=True is designed to speed up data transfers between the CPU (host) and GPU (accelerator) by using "page-locked" memory. When no accelerator is found, the training defaults to your CPU, making the memory-pinning step unnecessary.


## Upload the model

There is a script to upload the model, but you need to install all the python dependencies from requirements.txt first.
