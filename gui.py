import customtkinter as ctk
import psutil
import database


def launch_environment(briefing_text: str) -> None:
    """
    Launches the display GUI with the given briefing text, and live.
    Args:
        briefing_text (str): The text to display in the GUI.
    """
    ctk.set_appearance_mode("dark")
    
    root = ctk.CTk()
    root.title("APEX HUD")
    
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.9) 

    root.update_idletasks()
    width = 500
    height = 300
    screen_width = root.winfo_screenwidth()
    
    x_pos = screen_width - width - 20
    y_pos = 20
    root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    main_frame = ctk.CTkFrame(master=root, corner_radius=15, border_width=2, border_color="#1f538d")
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)

    title = ctk.CTkLabel(master=main_frame, text="APEX HUD", font=("Courier New", 14, "bold"), text_color="#1f538d")
    title.pack(pady=(10, 5))

    grid_frame = ctk.CTkFrame(master=main_frame, fg_color="transparent")
    grid_frame.pack(fill="both", expand=True, padx=10, pady=5)
    grid_frame.columnconfigure(0, weight=3)
    grid_frame.columnconfigure(1, weight=1)

    content = ctk.CTkTextbox(master=grid_frame, height=130, fg_color="#2b2b2b", font=("Consolas", 12), wrap="word")
    content.insert("0.0", briefing_text)
    content.configure(state="disabled") 
    content.grid(row=0, column=0, padx=(0, 10), sticky="nsew")

    diag_frame = ctk.CTkFrame(master=grid_frame, fg_color="transparent")
    diag_frame.grid(row=0, column=1, sticky="nsew")
    
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent

    ctk.CTkLabel(master=diag_frame, text="SYS DIAGNOSTICS", font=("Consolas", 11, "bold")).pack(anchor="w")
    
    ctk.CTkLabel(master=diag_frame, text=f"CPU: {cpu_usage}%", font=("Consolas", 10)).pack(anchor="w", pady=(5,0))
    cpu_bar = ctk.CTkProgressBar(master=diag_frame, height=8, progress_color="#1f538d")
    cpu_bar.set(cpu_usage / 100)
    cpu_bar.pack(fill="x", pady=(0, 5))

    ctk.CTkLabel(master=diag_frame, text=f"RAM: {ram_usage}%", font=("Consolas", 10)).pack(anchor="w")
    ram_bar = ctk.CTkProgressBar(master=diag_frame, height=8, progress_color="#1f538d")
    ram_bar.set(ram_usage / 100)
    ram_bar.pack(fill="x")

    reminder_frame = ctk.CTkFrame(master=main_frame, fg_color="transparent")
    reminder_frame.pack(fill="x", padx=10, pady=(10, 0))
    
    reminder_entry = ctk.CTkEntry(master=reminder_frame, placeholder_text="Enter new directive/reminder...", font=("Consolas", 11))
    reminder_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
    
    def log_reminder():
        """
        Captures the entry text and saves it to the database.
        """
        note = reminder_entry.get()
        if note.strip():
            database.save_reminder(note)
            print(f"DEBUG - Saved to DB: {note}")
            reminder_entry.delete(0, 'end')

    save_btn = ctk.CTkButton(master=reminder_frame, text="LOG", width=50, command=log_reminder, fg_color="#1f538d", hover_color="#14375e")
    save_btn.pack(side="right")

    close_btn = ctk.CTkButton(master=main_frame, text="DISMISS", command=root.destroy, width=120, height=28, fg_color="#333333", hover_color="#555555")
    close_btn.pack(pady=10)

    root.mainloop()

if __name__ == "__main__":
    launch_environment("SYSTEM ONLINE. Data streams synchronized. Awaiting command, Chief.")