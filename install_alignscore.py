import os
import subprocess
import sys

def main():
    repo_url = "https://github.com/yuh-zha/AlignScore.git"
    folder_name = "AlignScore"

    # 1. Clone the repo if it doesn't exist
    if not os.path.exists(folder_name):
        print(f"Cloning {repo_url}...")
        subprocess.run(["git", "clone", repo_url], check=True)
    else:
        print(f"Folder '{folder_name}' already exists. Skipping clone.")

    # 2. Modify pyproject.toml to remove the 'torch<2' restriction and 'protobuf<=3.20'
    toml_path = os.path.join(folder_name, "pyproject.toml")
    if os.path.exists(toml_path):
        print(f"Modifying {toml_path} to remove torch<2 constraint...")
        with open(toml_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove the torch <2 constraint
        content = content.replace('"torch>=1.12.1,<2"', '"torch>=1.12.1"')
        
        # Remove the protobuf<=3.20 constraint (to avoid installation issues on newer python versions)
        content = content.replace('"protobuf<=3.20"', '"protobuf"')

        with open(toml_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Successfully modified pyproject.toml!")
    else:
        print("Error: pyproject.toml not found in the cloned repo!")
        sys.exit(1)

    # 3. Install the modified package using pip
    print("Installing modified AlignScore package...")
    # Using sys.executable to ensure we install to the correct virtualenv/python environment
    subprocess.run([sys.executable, "-m", "pip", "install", f"./{folder_name}"], check=True)
    print("AlignScore installed successfully!")

if __name__ == "__main__":
    main()
