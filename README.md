# PwnedNext - An OWASP Cornucopia Companion Guide

F-Corp Ltd just finished coding their brand new multitenanted AI application "AI Anti-Fraud 3.0" to be used by their customers in the Fintech space.
This has caught the interest of PwnedNext a European company that sells solutions to a number of banks and financial institutions. They therefor have voiced their interest in buing F-Corp and their new AI system. 

But under Article 9 of the AI Act, any AI system classified as "high-risk" mandates the implementation of a comprehensive risk Management System throughout the entire lifecycle of the system. In order to identify foreseeable risks, PwnedNext is required to identify and analyze known and reasonably AI risks. This includes examining what happens when the system faces adversarial attacks or is misused, forcing a practical threat modeling process. F-Corp must therefor prove that their system is designed and developed to be robust, secure, and adequately protected against unauthorized access, data poisoning, and manipulation.

The current CEO of F-Corp is panicking after becoming aware that they haven't done any threat modelling or risk assessment during the development of AI Anti-Fraud 3.0, luckily the CTO has heard about this game called OWASP Cornucopia that can be used to do threat modeling of AI applications quickly in order to satisfy PwnedNext's threat modeling and risk management requirements. He immediatly urges all his junior AI developers and testers to come to getter for a OWASP Cornucopia session.

## Why you should you use this companion guide

If you have customers that need to comply with the AI Act or you have or want to have a certificate that proves you have a proper AI risk management system that covers controls that allowes you to develop and test AI functionality in a responsible way, then you need to implement the appropriate annext A controls according to the ISO 42001 standard.
The following controls are applicable in this regard:

- A.6.2 (Responsible AI Design and Development): Developers must be trained on how to apply ethical and safe design patterns. They need to understand principles like transparency, fairness, and safety boundaries during coding.
- A.6.3 (Verification and Validation): Testers and QA engineers must be trained in AI-specific testing methods. This includes evaluating model accuracy, checking for algorithmic drift, testing against adversarial attacks, and verifying 
- A.4.2 (Human Resources) mandates that organizations must ensure they have access to adequate human resources with the necessary AI expertise to develop systems safely. Training programs for internal developers and testers are standard evidence used to fulfill this control.

Through gamification, this game master guide introduce developers and testers to threats, risks, and requirements related to AI design and development and teaches how to mitigate against these risks. The game scenario takes the participants through a provocative scenario where they have to identify AI threats through studying an insecure AI implementation. They need to ask themselves "what can go wrong" and "what they (we) are going to do about it"? Further more, by playing, they will get to know about which tests from the OWASP AI Test Guide (AITG) and OWASP AI Security Verification Standard (AISVS) are needed to be looked at in order to responsibly develop AI applications.
They will also become familiar with AI attack techniques from Mitre Atlas and AI risks according to  OWASP Top 10 for LLM and  OWASP Top 10 for Agentic AI.

## ISO 42001

ISO 42001 operates as a broad, risk-based management framework that requires organizations to identify AI risks and ensure that all staff have the necessary competencies to execute their roles safely.
Instead of dictating a rigid training syllabus, the standard embeds learning and competence into its high-level clauses

- Clause 7.2 (Competence): Requires your organization to determine the necessary competence of all people doing work under its control that affects your AI performance and safety.
- Clause 7.3 (Awareness): Mandates that personnel are aware of the AI policy, their contribution to the effectiveness of the AI Management System (AIMS), and the implications of not conforming with AIMS requirements.

## Annex A Controls

ISO includes 38 optional risk management controls covering the AI lifecycle. If an organization's risk assessment identifies that an unskilled developer or tester poses a threat to AI safety (e.g., data poisoning, bias introduction), the organization must design and implement the appropriate training "control" to mitigate that specific risk.

## What this Training Covers

Because ISO 42001 ensures transparency, fairness, and accountability in AI, training for developers and testers typically encompasses:

- AI Literacy and Concepts: Understanding how the AI models function, their limitations, and intended applications.
- AI Risk Management: Learning how to spot vulnerabilities and biases within models.
- Data Quality Management: Ensuring that training and testing data are secure, unbiased, and compliant with privacy regulations.
- Ethical AI Principles: Prioritizing human oversight, safety, and non-discrimination during the design and testing phases.

This training is made specificly for covering these needs.

## Setup

Running the demo.
You need a laptop with at least 32GB memory to run this. Make sure everything else is shut down.

### Windows

If on Windows you need to edit your .wslconfig file. 

    # Visual Studio Code
    code $env:USERPROFILE\.wslconfig

    # Add the following 
    [wsl2]
    memory=32GB
    processors=8
    swap=12GB

Then run:

    wsl --shutdown

Start docker. Then...

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

## Tuning

It's possible to tune the model. The tuning functionality could be a great start for talking about supply chain attacks, but it need to be extended.

python -X utf8 .\tune.py

You may get the following message: 'pin_memory' argument is set as true but no accelerator is found, then device pinned memory won't be used.

This warning will not break your LLM training, but it can lead to minor efficiency issues or performance degradation.

In PyTorch, pin_memory=True is designed to speed up data transfers between the CPU (host) and GPU (accelerator) by using "page-locked" memory. When no accelerator is found, the training defaults to your CPU, making the memory-pinning step unnecessary.


## Upload the model

There is a script to upload the model, but you need to install all the python dependencies from requirements.txt first.