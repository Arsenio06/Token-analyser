import requests
import json
import os
import csv
import re  # For better parsing

# Install ddgs if not available
try:
    from ddgs import DDGS
except ImportError:
    os.system("pip install -q ddgs")
    from ddgs import DDGS

# Your xAI API key
API_KEY = "Your API Kei"
API_URL = "https://api.x.ai/v1/chat/completions"
MODEL = "grok-4-0709"  # Current xAI API model; note that Grok 4 may not be directly available via API yet, this approximates it

# Function to read links from file
def read_links(file_path="links.txt"):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"{file_path} not found.")
    with open(file_path, "r") as f:
        links = [line.strip() for line in f if line.strip()]
    return links

# Function to chunk links into groups of 10
def chunk_links(links, chunk_size=10):
    for i in range(0, len(links), chunk_size):
        yield links[i:i + chunk_size]

# Define tools for live-search
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Function to execute the tool
def execute_tool(tool_call):
    function_name = tool_call["function"]["name"]
    arguments = json.loads(tool_call["function"]["arguments"])
    
    if function_name == "search_web":
        query = arguments["query"]
        try:
            with DDGS() as ddgs:
                results = [r for r in ddgs.text(query, max_results=20)]  # Increased to 20 for more comprehensive results
            return json.dumps(results)
        except Exception as e:
            return f"Search failed: {str(e)}"
    return "Unknown tool"

# Function to send request to Grok API and handle tool calls in a loop
def send_to_grok(prompt):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Enhanced system prompt with structured output format
    messages = [
        {"role": "system", "content": """You are Grok 4, a helpful and maximally truthful AI. Analyze web3 projects based on their GitHub repos for launched tokens. For each project, search the web thoroughly for official information on whether they have a launched token, including token name, ticker, and launch date if applicable. Use the search_web tool multiple times if needed for accuracy. 

Structure your response exactly in this format for each project, one after another:

#Номер. Назва Проекту
GitHub URL: https://github.com/...
Наявність запущеного токена: Так or Ні
Назва токена: Тікер (якщо Так, інакше -)
Примітки: Детальний аналіз, включаючи дату запуску якщо є, і джерела.

Separate projects with a blank line. Respond in Ukrainian."""},
        {"role": "user", "content": prompt}
    ]
    
    max_iterations = 5  # Limit tool call loops to prevent infinite loops
    iteration = 0
    
    while iteration < max_iterations:
        payload = {
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "stream": False,
            "temperature": 0.7,  # Adjust for more creative/detailed responses
            "max_tokens": 4096  # Increase for longer, more detailed responses
        }
        
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            raise Exception(f"API request failed: {response.text}")
        
        response_data = response.json()
        assistant_message = response_data["choices"][0]["message"]
        
        # If there's content and no tool calls, return it
        if assistant_message.get("content") and "tool_calls" not in assistant_message:
            return assistant_message["content"]
        
        # Add assistant's message
        messages.append(assistant_message)
        
        # Process tool calls
        if "tool_calls" in assistant_message:
            for tool_call in assistant_message["tool_calls"]:
                tool_response = execute_tool(tool_call)
                messages.append({
                    "role": "tool",
                    "content": tool_response,
                    "tool_call_id": tool_call["id"]
                })
        
        iteration += 1
    
    raise Exception("Max tool iterations reached without final response.")

# Function to parse the response into structured data
def parse_response(response):
    data = []
    # Split by #Number. 
    sections = re.split(r'(#\d+\.\s+.+?)\n', response)
    i = 0
    while i < len(sections):
        if re.match(r'#\d+\.\s', sections[i]):
            project = {
                'Проект': sections[i].strip('#1234567890. ').strip(),
                'GitHub URL': '',
                'Наявність запущеного токена?': '',
                'Назва токена': '',
                'Примітки': ''
            }
            if i+1 < len(sections):
                content = sections[i+1].strip()
                # Parse lines
                lines = content.split('\n')
                for line in lines:
                    if line.startswith('GitHub URL:'):
                        project['GitHub URL'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Наявність запущеного токена:'):
                        project['Наявність запущеного токена?'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Назва токена:'):
                        project['Назва токена'] = line.split(':', 1)[1].strip()
                    elif line.startswith('Примітки:'):
                        project['Примітки'] = line.split(':', 1)[1].strip()
                    else:
                        project['Примітки'] += '\n' + line.strip()
                project['Примітки'] = project['Примітки'].strip()
            data.append(project)
        i += 2 if i+1 < len(sections) and not re.match(r'#\d+\.\s', sections[i+1]) else 1
    return data

# Function to save results to CSV
def save_results(data, file_path):
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Проект', 'GitHub URL', 'Наявність запущеного токена?', 'Назва токена', 'Примітки'])
        writer.writeheader()
        writer.writerows(data)
    print(f"Auto-saved results to {file_path} (partial)")

# Main function
def main():
    links = read_links()
    base_prompt = "Привіт, проведи аналіз web3 проектів, Github яких я тобі надіслав, на наявність запущеного токена."
    
    all_data = []
    csv_file = "results.csv"
    
    for i, chunk in enumerate(chunk_links(links), start=1):
        chunk_links_str = "\n".join(chunk)
        full_prompt = f"{base_prompt}\n{chunk_links_str}"
        
        print(f"Processing chunk {i}...")
        print("Prompt:")
        print(full_prompt)
        print("\nResponse:")
        try:
            response = send_to_grok(full_prompt)
            print(response)
            # Parse the response
            chunk_data = parse_response(response)
            all_data.extend(chunk_data)
            # Auto-save every 5 chunks (requests)
            if i % 5 == 0:
                save_results(all_data, csv_file)
        except Exception as e:
            print(f"Error: {e}")
        print("\n" + "-"*80 + "\n")
    
    # Final save
    save_results(all_data, csv_file)
    
    print(f"Results written to {csv_file}")

if __name__ == "__main__":
    main()
