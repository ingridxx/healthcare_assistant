import yaml
import os
import uuid
import datetime
import random
import time

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
yaml_file_path = os.path.join(script_dir, 'data.yaml')

def read_yaml():
    with open(yaml_file_path, 'r') as file:
        return yaml.safe_load(file)
    
def prompt_options(options):
    print("Please choose from the following options:")
    for i, option in enumerate(options, 1):
        print(f"{i}. {option}")

# Prompt the user to select an option
    while True:
        try:
            choice = int(input("Enter the number corresponding to your choice (eg, 1): "))
            if 1 <= choice <= 3:
                print(f"You chose: {options[choice - 1]}")
                return options[choice - 1]
            else:
                print(f"Invalid input. Please enter a number between 1 and {len(options)}.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

def generate_data(data_format):
    json_value = {}
    for value in data_format.keys():
        value_type = data_format[value]["type"]
        if value_type == "uuid":
            json_value[value] = uuid.uuid4().hex
        elif value_type == "timestamp":
            json_value[value] = datetime.datetime.now().isoformat()
        elif value_type == "choice":
            json_value[value] = random.choice(list(data_format[value]["values"]))
        elif value_type == "int":
            json_value[value] = random.randint(data_format[value]["min"], data_format[value]["max"])
        elif value_type == "decimal":
            # Random float (e.g., glucose level)
            min_val = data_format[value]["min"]
            max_val = data_format[value]["max"]
            json_value[value] = round(random.uniform(min_val, max_val), 2)
        if "prefix" in data_format[value]:
            json_value[value] = data_format[value]["prefix"] + str(json_value[value])
    return json_value



def main_generation(num_records):
    data = read_yaml()['data']
    data_types = list(data.keys())
    choice = prompt_options(data_types)
    print(choice)
    data_format = data[choice]

    event_logs = []
    for _ in range(num_records):
        row = generate_data(data_format)
        event_logs.append(row)
        print(row)
        time.sleep(1)
    return event_logs

# Testing purposes
if __name__ == "__main__":
    num_records = int(input("Enter the number of records to generate: "))
    main_generation(num_records)