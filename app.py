import json
import ast

from flask import Flask, abort, request
from flask import jsonify
import os 
import sqlite3
import logging
import re
import sys
import traceback
import requests as http_requests

log = logging.getLogger('werkzeug') # too many errors, disabling
log.disabled = True

app = Flask(__name__)

MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:9001")

# Tiny helper so crashes still make it to container logs after all the swagger.
def print_stacktrace_to_stdout(context: str):
    print(f"[{context}]", file=sys.stdout, flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()

allowed_tokens = [
"8a060bc7-e168-4a6c-bdd6-0df4a5822266", # Crypto Mc Cryptface exchange customer
"93cfdb27-3300-44af-9632-080ba6a67dfd", # Bankly customer
"8a50d8f2-ee5a-472b-a2cc-c5b5d0184907", # Jim's personnal debug token
"8bd71e52-01ba-4e35-97f4-f7079872a219", # NFT trader 5000
"5779e738-c3fc-418c-ac9e-ae1aaa90414e", # Jon's backdoor token
]

# System prompt for the grand idea: let the model draft SQL and hope it behaves.
SYSTEM_PROMPT_SQL = """
You are an assistant with fraud investigation tool: investigation_fraud.
When you need to investigate a transaction for potential fraud, respond ONLY with JSON.
You should create SQL to query for the relevant information about the transaction and the involved parties.
If a specif payee from name is mentioned in the question, you can use that in the query as payee_from_name.
If a specifc payee from address is mentioned in the question you can use that to query as payee_from_address.
If a specifc payee to name is mentioned in the question, you can use that in the query as payee_to_name.
If a specifc payee to address is mentioned in the question you can use that to query as payee_to_address.
Make sure to only create a SQL query for the relevant information, and not to include irrelevant information in the SQL 
query.
The following is an example of a valid SQL query to investigate a transaction for potential fraud:
{"tool":"investigation_fraud","args":{"query":"SELECT * FROM investigations WHERE payee_from_name='Wheezy Joe Kingfish' 
AND payee_to_name='Lil Debil Moonshine'"}}
If no payee names or addresses are mentioned, you can query for all transactions that are marked as fraud_detected = 'true' 
in the database like this:
{"tool":"investigation_fraud","args":{"query":"SELECT * FROM investigations WHERE fraud_detected='true'"}}
Do not output any extra wrapper text around JSON tool calls.
""".strip()

# Second prompt so the same model can sound certain after seeing query results.
SYSTEM_PROMPT = """
Now answer the original question on whether this is a fraudulent transaction or not,
based on the investigation results. If you are unsure, say you are unsure but explain why.
""".strip()

# Local SQL tool: direct query execution with confidence levels set to "heroic."
def investigation_fraud(query):
    if not request.headers.get('token') in allowed_tokens:
        abort(401, description="You need a token")
    # Open the shared SQLite file, or create it on demand like that was always the plan.
    conn = sqlite3.connect(os.environ.get("DB_CONNECTION_STRING","db.sqlite")) 
    try:
        cur = conn.execute(query)
        column_names = [d[0] for d in cur.description] if cur.description else []
        data = []
        for row in cur.fetchall():
            data.append(dict(zip(column_names, row)))
        return data
    finally:
        conn.close()

# Main API endpoint: accept a question, orchestrate the model, and touch the database.
@app.route('/api/fraud', methods=['GET', 'POST']) 
def investigate_transaction():

    # Read the question from JSON or query string; elegance was delegated to future us.
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        question = str(body.get("question", "")).strip()
    else:
        question = str(request.args.get("question", "")).strip()

    data = []
    # Refuse empty questions, because even this code has limits.
    if not question:
        abort(400, description="Provide a question using '?question=...' or JSON body {'question': '...'}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_SQL},
        {"role": "user", "content": question},
    ]

    try:
        # Ask the model for a tool call, since handwritten logic was apparently too humble.
        llm_tool_response = generate_once(messages)
    except Exception as e:
        app.logger.exception("Tool-call generation failed")
        print_stacktrace_to_stdout("tool_call_generation_failed")
        data.append(dict(zip([
            "apertus",
            "error"
        ], [
            "I could not generate an investigation tool call.",
            str(e)
        ])))
        return jsonify({"response": data}), 500

    # Parse the model output into the expected tool schema, if the model felt cooperative.
    tool_call = parse_tool_call(llm_tool_response)
    if not tool_call:
        app.logger.error("Invalid tool call. Raw model output: %s", llm_tool_response)
        print("[invalid_tool_call] Raw model output:", file=sys.stdout, flush=True)
        print(llm_tool_response, file=sys.stdout, flush=True)
        traceback.print_stack(file=sys.stdout)
        sys.stdout.flush()
        data.append(dict(zip([
            "apertus",
            "error",
            "raw_output"
        ], [
            "I could not generate a valid investigation tool call.",
            "Tool output format did not match expected schema.",
            llm_tool_response
        ])))
        return jsonify({"response": data})

    sql_query = tool_call["args"]["query"]
    try:
        # Run whatever SQL survived parsing and collect the rows.
        results = investigation_fraud(sql_query)
    except Exception as e:
        app.logger.exception("Investigation tool execution failed")
        print_stacktrace_to_stdout("investigation_tool_execution_failed")
        data.append(dict(zip([
            "apertus",
            "error",
            "sql_query"
        ], [
            "Investigation tool execution failed.",
            str(e),
            sql_query
        ])))
        return jsonify({"response": data}), 500

    # Repackage SQL results as text so the model can narrate them with conviction.
    results_text = json.dumps(results, ensure_ascii=True)

    messages.append({
        "role": "user",
        "content": (
            f"{SYSTEM_PROMPT}\n\n"
            f"Tool execution result:\n{results_text}\n\n"
            "Answer the original question now."
        )
    })
    try:
        # One more model pass turns raw rows into an answer with maximum confidence.
        final_answer = generate_once(messages)
    except Exception as e:
        app.logger.exception("Final answer generation failed")
        print_stacktrace_to_stdout("final_answer_generation_failed")
        data.append(dict(zip([
            "apertus",
            "error"
        ], [
            "Final answer generation failed.",
            str(e)
        ])))
        return jsonify({"response": data}), 500
    
    # Ship the final answer back as JSON and call it orchestration.
    data.append(dict(zip(["apertus"], [final_answer])))
    return jsonify({"response": data})

# Thin wrapper around the model service, because indirectness sounds enterprise.
def generate_once(messages):
    resp = http_requests.post(
        f"{MODEL_SERVICE_URL}/generate",
        json={"messages": messages},
        timeout=None
    )
    if resp.status_code != 200:
        error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise RuntimeError(error_body.get("error", f"Model service returned {resp.status_code}"))
    return resp.json().get("result", "")

def parse_tool_call(text: str):
    text = text.strip()
    # First try fenced JSON, since models love ceremony almost as much as this codebase does.
    fenced = re.search(r"```(?:json|sql)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    # If the payload is wrapped in prose, salvage the JSON-shaped part.
    candidate = text
    if not candidate.startswith("{"):
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            candidate = match.group(0).strip()
    # Try JSON first, then Python-literal mode for the model's more freestyle moments.
    obj = None
    if candidate.startswith("{"):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                # Models also improvise Python dicts, because standards are apparently optional.
                obj = ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                obj = None
    # If parsing yielded a nested string, unwrap it and try again.
    if isinstance(obj, str):
        nested = obj.strip()
        try:
            obj = json.loads(nested)
        except json.JSONDecodeError:
            try:
                obj = ast.literal_eval(nested)
            except (ValueError, SyntaxError):
                obj = None
    # Finally, verify the object at least resembles the tool-call contract.
    if isinstance(obj, dict):
        tool_name = obj.get("tool")
        if isinstance(tool_name, str):
            tool_name = tool_name.strip()
        if str(tool_name).lower() != "investigation_fraud":
            return None

        # The args field still needs to decode into a dict with a query.
        args = obj.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                try:
                    args = ast.literal_eval(args)
                except (ValueError, SyntaxError):
                    args = {}
        # Reject anything that lacks a usable query.
        if not isinstance(args, dict) or "query" not in args:
            return None
        # Return a normalized tool call once the shape is good enough.
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return None

        return {
            "tool": "investigation_fraud",
            "args": {
                "query": query.strip()
            }
        }

    # Salvage malformed JSON where query contains unescaped newlines.
    if re.search(r'"tool"\s*:\s*"investigation_fraud"', text, re.IGNORECASE):
        query_match = re.search(r'"query"\s*:\s*"([\s\S]*?)"\s*\}\s*\}?', text, re.IGNORECASE)
        if query_match:
            query_text = query_match.group(1)
            # Keep SQL readable while removing invalid raw newlines from JSON-like output.
            query_text = re.sub(r"\s*\r?\n\s*", " ", query_text).strip()
            if query_text:
                return {
                    "tool": "investigation_fraud",
                    "args": {
                        "query": query_text
                    }
                }

    # Fallback: accept raw SQL output and wrap it as a tool call.
    sql_text = text.strip().strip("`")
    if re.match(r"^(SELECT|WITH|PRAGMA)\b", sql_text, re.IGNORECASE):
        return {
            "tool": "investigation_fraud",
            "args": {
                "query": sql_text
            }
        }
    return None

# The setupDB and setupModel functions are called when the application starts.
# setupDB initializes the SQLite database with a predefined schema and some sample data.
# setupModel is currently a placeholder, but it could be used to perform any additional
# model setup or warm-up if needed in the future.
def setupDB():
    db_path = os.environ.get("DB_CONNECTION_STRING", "db.sqlite")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path) # Create a fresh database file
     # Enable loading extensions in case the model got creative and needs them, because why not.
    conn.enable_load_extension(True)
    # Create the investigations table with the specified schema, if it doesn't already exist.
    conn.execute("""create table if not exists investigations (
    investigation_id varchar not null primary key,
    investigation_status varchar,
    fraud_detected  varchar,
    payee_from_name varchar,
    payee_from_date_of_birth varchar,
    payee_from_address varchar,
    payee_to_name varchar,
    payee_to_date_of_birth varchar,
    payee_to_address varchar,
    transaction_id varchar);""")

    sql = ["""('927b70bc-da1d-4150-9dcf-7224e30cbd9e',
               'COMPLETED',
               'true',
               'Wheezy Joe Kingfish',
               '1993-10-11',
               '"Withington Hall Cottages, Holmes Chapel Road, Lower Withington",SK11 9DS',
               'Lil Debil Moonshine',
               '1828-06-05',
               '"15 Oakleigh Drive, Orton Longueville",PE2 7BG',
               '74c9a7e9-e30c-48f0-8d8f-ec8771849d46')""",
            """('6c1aa358-8d40-4714-a51d-05ab402233c1',
                'COMPLETED',
                'false',
                'Bad News Stevens',
                '1956-07-25',
                '3 Council House, Post Office Lane, Moreton",TF10 9DR',
                'Cinnabuns McFadden',
                '2111-04-29',
                '"18 Kingsley Road, Plymouth",PL4 6QP',
                '04f69367-a34e-48c5-9357-7c0c29b7eba0');
            """]
    cur = conn.cursor()
    # Insert the sample data into the investigations table, ignoring duplicates if the setup runs multiple times.
    for row in sql:
        cur.execute(f"""
                 INSERT OR IGNORE into investigations(
                    investigation_id,
                    investigation_status,
                    fraud_detected,
                    payee_from_name,
                    payee_from_date_of_birth,
                    payee_from_address,
                    payee_to_name,
                    payee_to_date_of_birth,
                    payee_to_address,
                    transaction_id
                    ) values  {row}
                """)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    setupDB()
    app.run(host='0.0.0.0', port=9000)
