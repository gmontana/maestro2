import os
import re
from datetime import datetime
import json
from rich.console import Console
from rich.panel import Panel
import ollama
from ollama import Client  # Import the Ollama client
import argparse

# Only for the first time run based on the model you want to use
# ollama.pull('llama3:70b')
# ollama.pull('llama3:8b')
# ollama.pull('llama3:8b')
ollama.pull('llama3:70b-instruct')
# ollama.pull('llama3:instruct')

# Define model identifiers as variables at the top of the script
MODEL_IDENTIFIERS = {
    'ORCHESTRATOR_MODEL': 'llama3:70b-instruct',
    'SUBAGENT_MODEL': 'llama3:instruct',
    'REFINER_MODEL': 'llama3:70b-instruct'
}

def check_and_pull_models(models):
    """
    Check and pull models if they don't exist.
    :param models: A dictionary of model identifiers.
    """
    for model_name, model_id in models.items():
        try:
            print(f"Checking for model: {model_id}")
            ollama.show(model_id)
        except ollama._types.ResponseError:
            print(f"Pulling model from ollama: {model_id}")
            ollama.pull(model_id)

check_and_pull_models(MODEL_IDENTIFIERS)
# Initialize the Ollama client
client = Client(host='http://localhost:11434')

console = Console()

def opus_orchestrator(objective, file_content=None, previous_results=None):
    """
    Calls the Ollama Orchestrator to break down the objective into sub-tasks or provide the final output.
    :param objective: The main objective to be achieved.
    :param file_content: Optional content of a file related to the objective.
    :param previous_results: Results from previous sub-tasks, if any.
    :return: A tuple containing the orchestrator's response and the file content.
    """
    console.print(f"\n[bold]Calling Ollama Orchestrator for your objective[/bold]")
    previous_results_text = "\n".join(previous_results) if previous_results else "None"
    display_file_content_panel(file_content)

    response_text = send_ollama_request(ORCHESTRATOR_MODEL, objective, file_content, previous_results_text)
    display_response_panel(response_text, "Ollama Orchestrator")
    return response_text, file_content

def display_file_content_panel(file_content):
    """
    Displays the file content in a panel if file content is provided.
    :param file_content: The content of the file to be displayed.
    """
    if file_content:
        console.print(Panel(f"File content:\n{file_content}", title="[bold blue]File Content[/bold blue]", title_align="left", border_style="blue"))

def send_ollama_request(model, objective, file_content, previous_results_text):
    """
    Sends a request to the Ollama service.
    :param model: The model to use for the request.
    :param objective: The main objective of the request.
    :param file_content: Optional content of a file related to the objective.
    :param previous_results_text: Text representation of previous results.
    :return: The response text from Ollama.
    """
    response = client.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": generate_ollama_prompt(objective, file_content, previous_results_text)
        }]
    )
    return response['message']['content']

def display_response_panel(response_text, title):
    """
    Displays the response text in a panel.
    :param response_text: The text to display in the panel.
    :param title: The title of the panel.
    """
    console.print(Panel(response_text, title=f"[bold green]{title}[/bold green]", title_align="left", border_style="green", subtitle="Sending task to Ollama sub-agent 👇"))

def generate_ollama_prompt(objective, file_content, previous_results_text):
    """
    Generates the prompt to send to Ollama based on the objective, file content, and previous results.
    :param objective: The main objective of the request.
    :param file_content: Optional content of a file related to the objective.
    :param previous_results_text: Text representation of previous results.
    :return: The generated prompt for Ollama.
    """
    return f"Based on the following objective{' and file content' if file_content else ''}, and the previous sub-task results (if any), please break down the objective into the next sub-task, and create a concise and detailed prompt for a subagent so it can execute that task. Focus solely on the objective and avoid engaging in casual conversation with the subagent.\n\nWhen dealing with code tasks, make sure to check the code for errors and provide fixes and support as part of the next sub-task. If you find any bugs or have suggestions for better code, please include them in the next sub-task prompt.\n\nPlease assess if the objective has been fully achieved. If the previous sub-task results comprehensively address all aspects of the objective, include the phrase 'The task is complete:' at the beginning of your response. If the objective is not yet fully achieved, break it down into the next sub-task and create a concise and detailed prompt for a subagent to execute that task.\n\nObjective: {objective}" + (f'\nFile content:\n{file_content}' if file_content else '') + f"\n\nPrevious sub-task results:\n{previous_results_text}"


def haiku_sub_agent(prompt, previous_haiku_tasks=None, continuation=False):
    if previous_haiku_tasks is None:
        previous_haiku_tasks = []

    continuation_prompt = "Continuing from the previous answer, please complete the response."
    if continuation:
        prompt = continuation_prompt

    # Compile previous tasks into a readable format
    previous_tasks_summary = "Previous Haiku tasks:\n" + \
        "\n".join(
            f"Task: {task['task']}\nResult: {task['result']}" for task in previous_haiku_tasks)

    # Append previous tasks summary to the prompt
    full_prompt = f"{previous_tasks_summary}\n\n{prompt}"

    # Ensure prompt is not empty
    if not full_prompt.strip():
        raise ValueError("Prompt cannot be empty")

    response = client.chat(
        model=SUBAGENT_MODEL,
        messages=[{"role": "user", "content": full_prompt}]
    )

    response_text = response['message']['content']

    if len(response_text) >= 4000:  # Threshold set to 4000 as a precaution
        console.print(
            "[bold yellow]Warning:[/bold yellow] Output may be truncated. Attempting to continue the response.")
        continuation_response_text = haiku_sub_agent(
            continuation_prompt, previous_haiku_tasks, continuation=True)
        response_text += continuation_response_text

    console.print(Panel(response_text, title="[bold blue]Ollama Sub-agent Result[/bold blue]", title_align="left",
                  border_style="blue", subtitle="Task completed, sending result to Ollama Orchestrator 👇"))
    return response_text


def opus_refine(objective, sub_task_results, filename, projectname, continuation=False):
    console.print(
        "\nCalling Ollama to provide the refined final output for your objective:")

    response = client.chat(
        model=REFINER_MODEL,
        messages=[
            {
                "role": "user",
                "content": "Objective: " + objective + "\n\nSub-task results:\n" + "\n".join(sub_task_results) + "\n\nPlease review and refine the sub-task results into a cohesive final output. Add any missing information or details as needed.\n\nWhen working on code projects, ONLY AND ONLY IF THE PROJECT IS CLEARLY A CODING ONE, please provide the following:\n\n1. Project Name: Create a concise and appropriate project name that fits the project based on what it's creating. The project name should be no more than 20 characters long.\n\n2. Folder Structure: Provide the folder structure as a valid JSON object, where each key represents a folder or file, and nested keys represent subfolders. Use null values for files. Ensure the JSON is properly formatted without any syntax errors. Please make sure all keys are enclosed in double quotes, and ensure objects are correctly encapsulated with braces, separating items with commas as necessary. Wrap the JSON object in <folder_structure> tags.\n\n3. Code Files: For each code file, include ONLY the file name, NEVER EVER USE THE FILE PATH OR ANY OTHER FORMATTING. YOU ONLY USE THE FOLLOWING format 'Filename: <filename>' followed by the code block enclosed in triple backticks, with the language identifier after the opening backticks, like this:\n\npython\n<code>\n\n\nFocus solely on the objective and avoid engaging in casual conversation. Ensure the final output is clear, concise, and addresses all aspects of the objective.​"
            }
        ]
    )

    response_text = response['message']['content']

    if len(response_text) >= 4000:  # Threshold set to 4000 as a precaution
        console.print(
            "[bold yellow]Warning:[/bold yellow] Output may be truncated. Attempting to continue the response.")
        continuation_response_text = opus_refine(
            objective, sub_task_results, filename, projectname, continuation=True)
        response_text += continuation_response_text

    console.print(Panel(
        response_text, title="[bold green]Final Output[/bold green]", title_align="left", border_style="green"))
    return response_text


def create_folder_structure(project_name, folder_structure, code_blocks):
    try:
        os.makedirs(project_name, exist_ok=True)
        console.print(Panel(f"Created project folder: [bold]{project_name}[/bold]",
                      title="[bold blue]Project Folder Creation[/bold blue]", title_align="left", border_style="blue"))
    except OSError as e:
        console.print(Panel(f"Error creating project folder: [bold]{project_name}[/bold]\nError: {e}",
                      title="[bold red]Project Folder Creation Error[/bold red]", title_align="left", border_style="red"))

    create_folders_and_files(project_name, folder_structure, code_blocks)


def create_folders_and_files(current_path, structure, code_blocks):
    for key, value in structure.items():
        path = os.path.join(current_path, key)
        if isinstance(value, dict):
            try:
                os.makedirs(path, exist_ok=True)
                console.print(Panel(
                    f"Created folder: [bold]{path}[/bold]", title="[bold blue]Folder Creation[/bold blue]", title_align="left", border_style="blue"))
                create_folders_and_files(path, value, code_blocks)
            except OSError as e:
                console.print(Panel(f"Error creating folder: [bold]{path}[/bold]\nError: {e}",
                              title="[bold red]Folder Creation Error[/bold red]", title_align="left", border_style="red"))
        else:
            code_content = next(
                (code for file, code in code_blocks if file == key), None)
            if code_content:
                try:
                    with open(path, 'w') as file:
                        file.write(code_content)
                    console.print(Panel(
                        f"Created file: [bold]{path}[/bold]", title="[bold green]File Creation[/bold green]", title_align="left", border_style="green"))
                except IOError as e:
                    console.print(Panel(f"Error creating file: [bold]{path}[/bold]\nError: {e}",
                                  title="[bold red]File Creation Error[/bold red]", title_align="left", border_style="red"))
            else:
                console.print(Panel(
                    f"Code content not found for file: [bold]{key}[/bold]", title="[bold yellow]Missing Code Content[/bold yellow]", title_align="left", border_style="yellow"))


def read_file(file_path):
    with open(file_path, 'r') as file:
        content = file.read()
    return content


# parse args
parser = argparse.ArgumentParser()
parser.add_argument('-p', '--prompt', type=str,
                    help='Please enter your objective with or without a text file path')
args = parser.parse_args()

if args.prompt is not None:
    objective = args.prompt
else:
    # Get the objective from user input
    objective = input(
        "Please enter your objective with or without a text file path: ")

# Check if the input contains a file path
if "./" in objective or "/" in objective:
    # Extract the file path from the objective
    file_path = re.findall(r'[./\w]+\.[\w]+', objective)[0]
    # Read the file content
    with open(file_path, 'r') as file:
        file_content = file.read()
    # Update the objective string to remove the file path
    objective = objective.split(file_path)[0].strip()
else:
    file_content = None

task_exchanges = []
haiku_tasks = []

while True:
    # Call Orchestrator to break down the objective into the next sub-task or provide the final output
    previous_results = [result for _, result in task_exchanges]
    if not task_exchanges:
        # Pass the file content only in the first iteration if available
        opus_result, file_content_for_haiku = opus_orchestrator(
            objective, file_content, previous_results)
    else:
        opus_result, _ = opus_orchestrator(
            objective, previous_results=previous_results)

    if "The task is complete:" in opus_result:
        # If Opus indicates the task is complete, exit the loop
        final_output = opus_result.replace("The task is complete:", "").strip()
        break
    else:
        sub_task_prompt = opus_result
        # Append file content to the prompt for the initial call to haiku_sub_agent, if applicable
        if file_content_for_haiku and not haiku_tasks:
            sub_task_prompt = f"{sub_task_prompt}\n\nFile content:\n{file_content_for_haiku}"
        # Call haiku_sub_agent with the prepared prompt and record the result
        sub_task_result = haiku_sub_agent(sub_task_prompt, haiku_tasks)
        # Log the task and its result for future reference
        haiku_tasks.append(
            {"task": sub_task_prompt, "result": sub_task_result})
        # Record the exchange for processing and output generation
        task_exchanges.append((sub_task_prompt, sub_task_result))
        # Prevent file content from being included in future haiku_sub_agent calls
        file_content_for_haiku = None

# Create the .md filename
sanitized_objective = re.sub(r'\W+', '_', objective)
timestamp = datetime.now().strftime("%H-%M-%S")

# Call Opus to review and refine the sub-task results
refined_output = opus_refine(
    objective, [result for _, result in task_exchanges], timestamp, sanitized_objective)

# Extract the project name from the refined output
project_name_match = re.search(r'Project Name: (.*)', refined_output)
project_name = project_name_match.group(
    1).strip() if project_name_match else sanitized_objective

# Extract the folder structure from the refined output
folder_structure_match = re.search(
    r'<folder_structure>(.*?)</folder_structure>', refined_output, re.DOTALL)
folder_structure = {}
if folder_structure_match:
    json_string = folder_structure_match.group(1).strip()
    try:
        folder_structure = json.loads(json_string)
    except json.JSONDecodeError as e:
        console.print(Panel(
            f"Error parsing JSON: {e}", title="[bold red]JSON Parsing Error[/bold red]", title_align="left", border_style="red"))
        console.print(Panel(f"Invalid JSON string: [bold]{json_string}[/bold]",
                      title="[bold red]Invalid JSON String[/bold red]", title_align="left", border_style="red"))

# Extract code files from the refined output
code_blocks = re.findall(
    r'Filename: (\S+)\s*```[\w]*\n(.*?)\n```', refined_output, re.DOTALL)

# Create the folder structure and code files
create_folder_structure(project_name, folder_structure, code_blocks)

# Truncate the sanitized_objective to a maximum of 50 characters
max_length = 25
truncated_objective = sanitized_objective[:max_length] if len(
    sanitized_objective) > max_length else sanitized_objective

# Update the filename to include the project name
filename = f"{timestamp}_{truncated_objective}.md"

# Prepare the full exchange log
exchange_log = f"Objective: {objective}\n\n"
exchange_log += "=" * 40 + " Task Breakdown " + "=" * 40 + "\n\n"
for i, (prompt, result) in enumerate(task_exchanges, start=1):
    exchange_log += f"Task {i}:\n"
    exchange_log += f"Prompt: {prompt}\n"
    exchange_log += f"Result: {result}\n\n"

exchange_log += "=" * 40 + " Refined Final Output " + "=" * 40 + "\n\n"
exchange_log += refined_output

console.print(f"\n[bold]Refined Final output:[/bold]\n{refined_output}")

with open(filename, 'w') as file:
    file.write(exchange_log)
print(f"\nFull exchange log saved to {filename}")
