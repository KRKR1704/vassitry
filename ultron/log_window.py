import os
import threading
import time
import tkinter as tk
from tkinter import scrolledtext


def _tail_file_lines(path, last_pos=0):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_pos)
            data = f.read()
            return data, f.tell()
    except Exception:
        return "", last_pos


def _show_log_window(log_path: str):
    root = tk.Tk()
    root.title("Ultron — Logs")
    root.geometry("700x420")

    txt = scrolledtext.ScrolledText(root, state="disabled", wrap="word")
    txt.pack(fill="both", expand=True)

    last_pos = 0

    def append(s: str):
        try:
            txt.configure(state="normal")
            txt.insert("end", s)
            txt.see("end")
            txt.configure(state="disabled")
        except Exception:
            pass

    def poll():
        nonlocal last_pos
        try:
            if os.path.exists(log_path):
                data, last_pos = _tail_file_lines(log_path, last_pos)
                if data:
                    append(data)
        except Exception:
            pass
        root.after(500, poll)

    poll()
    try:
        root.mainloop()
    except Exception:
        pass


def start_log_window_thread(log_path: str):
    t = threading.Thread(target=_show_log_window, args=(log_path,), daemon=True)
    t.start()
