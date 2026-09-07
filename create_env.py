import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox

def load_existing_env():
    #Load existing .env values if the file already exists.
    env_data = {}
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env_data[key.strip()] = val.strip().strip('"').strip("'")
    return env_data


def save_env():
    token = entry_token.get().strip()
    api_key = entry_key.get().strip()
    api_url = entry_url.get().strip()

    if not token or not api_key or not api_url:
        messagebox.showwarning("Incomplete Fields", "Please fill in all fields before saving.")
        return

    env_content = (
        f'DISCORD_BOT_TOKEN="{token}"\n'
        f'AI_API_KEY="{api_key}"\n'
        f'API_URL="{api_url}"\n'
    )

    #Write the .env file
    try:
        with open(".env", "w", encoding="utf-8") as f:
            f.write(env_content)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save .env file:\n{e}")
        return

    #Launch the bot
    try:
        subprocess.Popen([sys.executable, "IIrumixDnD.py"])
        messagebox.showinfo("Success", ".env saved and bot launched successfully!")
        root.destroy()
    except Exception as e:
        messagebox.showerror("Execution Error", f"Failed to launch IIrumixDnD.py:\n{e}")


# Initialize UI window
root = tk.Tk()
root.title("Discord Bot Environment Setup")
root.geometry("450x260")
root.resizable(False, False)

existing_values = load_existing_env()

# UI Layout
padding_opts = {"padx": 12, "pady": 6}

# Discord Bot Token
tk.Label(root, text="Discord Bot Token:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **padding_opts)
entry_token = tk.Entry(root, width=55, show="*")
entry_token.pack(padx=12, fill="x")
if "DISCORD_BOT_TOKEN" in existing_values:
    entry_token.insert(0, existing_values["DISCORD_BOT_TOKEN"])

# AI API Key
tk.Label(root, text="AI API Key:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **padding_opts)
entry_key = tk.Entry(root, width=55, show="*")
entry_key.pack(padx=12, fill="x")
if "AI_API_KEY" in existing_values:
    entry_key.insert(0, existing_values["AI_API_KEY"])

# API URL
tk.Label(root, text="API Base URL:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **padding_opts)
entry_url = tk.Entry(root, width=55)
entry_url.pack(padx=12, fill="x")
if "API_URL" in existing_values:
    entry_url.insert(0, existing_values["API_URL"])
else:
    entry_url.insert(0, "https://api.experientiallabs.ai/v1")

# Save Button
btn_save = tk.Button(
    root,
    text="Start the Bot",
    command=save_env,
    bg="#4CAF50",
    fg="white",
    font=("Segoe UI", 10, "bold"),
    pady=4,
    cursor="hand2",
)
btn_save.pack(pady=15)

root.mainloop()