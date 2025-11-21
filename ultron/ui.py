import os
import threading
import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHUTDOWN_FLAG = os.path.join(BASE_DIR, "shutdown.flag")

# A thread-safe queue where the application pushes messages for the UI
_UI_QUEUE: "queue.Queue[str]" = queue.Queue()


def enqueue(msg: str) -> None:
    try:
        _UI_QUEUE.put_nowait(str(msg))
    except Exception:
        pass


def _write_shutdown_flag():
    try:
        with open(SHUTDOWN_FLAG, "w") as f:
            f.write("stop")
    except Exception:
        pass


def show_ui():
    # Run the Tk UI (designed to be started in its own thread)
    root = tk.Tk()
    root.title("Ultron — Background Controller")
    root.geometry("520x360")
    root.resizable(True, True)

    lbl = tk.Label(root, text="Ultron — Transcript / Activity", anchor="w", font=(None, 11, "bold"))
    lbl.pack(fill="x", padx=8, pady=(8, 4))

    txt = scrolledtext.ScrolledText(root, state="disabled", wrap="word", height=15)
    txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _append_line(line: str):
        try:
            txt.configure(state="normal")
            txt.insert("end", line + "\n")
            txt.see("end")
            txt.configure(state="disabled")
        except Exception:
            pass

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=8, pady=(0, 8))

    def on_stop():
        if messagebox.askyesno("Stop Ultron", "Stop Ultron now? This will shut down the background assistant."):
            _write_shutdown_flag()
            messagebox.showinfo("Stopping", "Shutdown requested. Ultron will stop shortly.")

    def on_open_logs():
        try:
            os.startfile(os.path.join(BASE_DIR, "logs"))
        except Exception:
            messagebox.showerror("Error", "Could not open logs folder.")

    stop_btn = tk.Button(btn_frame, text="Stop Ultron", command=on_stop, bg="#d9534f", fg="white")
    stop_btn.pack(side="left", padx=(0, 6))

    logs_btn = tk.Button(btn_frame, text="Open Logs", command=on_open_logs)
    logs_btn.pack(side="left", padx=(6, 6))

    hide_btn = tk.Button(btn_frame, text="Hide", command=root.withdraw)
    hide_btn.pack(side="right")

    # Poll the queue periodically and append messages
    def _poll():
        try:
            while True:
                try:
                    line = _UI_QUEUE.get_nowait()
                except queue.Empty:
                    break
                _append_line(line)
        except Exception:
            pass
        root.after(200, _poll)

    root.after(200, _poll)

    try:
        root.mainloop()
    except Exception:
        pass


def start_ui_thread():
    t = threading.Thread(target=show_ui, daemon=True)
    t.start()

