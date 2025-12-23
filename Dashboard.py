import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import FuncFormatter
import subprocess
import threading
import re
import os

class DamageTracker(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.log_process = None
        self.running = True

        w = 1440
        h = 810

        self.title("Damage Cap")
        self.geometry(f"{w}x{h}")
        ctk.set_appearance_mode("dark")

        self.damage_history = [0]
        self.max_hit = 0
        self.total_hits_above_cap = 1
        self.all_hits = []

        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        #Stats view
        self.stats_view = ctk.CTkFrame(self.top_frame, fg_color="#111111", width=(w * 0.5))
        self.stats_view.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.max_hit_lbl = ctk.CTkLabel(self.stats_view, text="LARGEST: 0", font=("Consolas", 32, "bold"), text_color="#f1c40f")
        self.max_hit_lbl.pack(pady=20)
        self.recent_hit_lbl = ctk.CTkLabel(self.stats_view, text="RECENT: 0", font=("Consolas", 32), text_color="white")
        self.recent_hit_lbl.pack(pady=20)
        self.avg_hit_lbl = ctk.CTkLabel(self.stats_view, text="AVERAGE: 0", font=("Consolas", 32), text_color="#3498db")
        self.avg_hit_lbl.pack(pady=20)
        self.count_lbl = ctk.CTkLabel(self.stats_view, text="HITS OVER CAP: 0", font=("Consolas", 32), text_color="#e74c3c")
        self.count_lbl.pack(pady=20)

        #List view
        self.list_view = ctk.CTkTextbox(self.top_frame, state="disabled", fg_color="#111111", text_color="white", font=("Consolas", 24))
        self.list_view.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        #Graph view
        self.bottom_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", height=400)
        self.bottom_frame.pack(side="bottom", fill="both", expand=True, padx=10, pady=5)
        self.fig, self.ax = plt.subplots(figsize=(10, 4), facecolor='#1a1a1a')
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.bottom_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        self.style_graph()

        threading.Thread(target=self.listen_to_logs, daemon=True).start()

    def format_damage_labels(self, x, pos=0):
        if x >= 1e18: 
            return f'{x*1e-18:.1f}Q'
        if x >= 1e15: 
            return f'{x*1e-15:.1f}P'
        if x >= 1e12: 
            return f'{x*1e-12:.1f}T'
        if x >= 1e9:  
            return f'{x*1e-9:.1f}B'
        if x >= 1e6:  
            return f'{x*1e-6:.1f}M'
        return f'{int(x)}'

    def style_graph(self):
        self.ax.set_facecolor('#1a1a1a')
        self.ax.tick_params(colors='white', which='both')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')

        self.ax.yaxis.set_major_formatter(FuncFormatter(self.format_damage_labels))

        for spine in self.ax.spines.values():
            spine.set_color('#444444')

        self.ax.grid(True, color='#333333', linestyle='--', alpha=0.5)

    def listen_to_logs(self):
        cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Content \\"$env:LOCALAPPDATA\\Warframe\\EE.log\\" -Wait -Tail 0 | Select-String \'Damage too high\''
        self.log_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, shell=True)

        for line in iter(self.log_process.stdout.readline, ""):
            if not self.running: 
                break
            if "after illumination" in line: 
                continue
            match = re.search(r"Damage too high: ([\d,]+)", line)
            if match:
                val = int(match.group(1).replace(',', ''))
                self.after(0, self.update_data, val, match.group(1))

    def update_data(self, val, raw):
        self.damage_history.append(val)
        self.all_hits.append(val)
        if len(self.damage_history) > 200:
            self.damage_history.pop(0)

        if val > self.max_hit: 
            self.max_hit = val
        
        if val > 0:
            self.total_hits_above_cap += 1

        avg_val = sum(self.all_hits) / self.total_hits_above_cap

        self.list_view.configure(state="normal")
        self.list_view.tag_config("Max", foreground="#00ff00")
        self.list_view.tag_config("Hit", foreground="#ffffff")
        if val == self.max_hit:
            self.list_view.insert("end", f"New Max!: {self.format_damage_labels(val)}, Raw: {raw}\n", "Max")
        else:
            self.list_view.insert("end", f"Hit: {self.format_damage_labels(val)}, Raw: {raw}\n", "Hit")
        self.list_view.see("end")
        self.list_view.configure(state="disabled")

        self.ax.clear()
        self.style_graph()
        
        self.ax.plot(self.damage_history, color="#f1c40f", linewidth=2)
        self.ax.axhline(y=self.max_hit, color='#e74c3c', linestyle='--', label="Max Hit")
        
        self.fig.tight_layout()
        self.canvas.draw()

        self.max_hit_lbl.configure(text=f"LARGEST: {self.format_damage_labels(self.max_hit)}")
        self.recent_hit_lbl.configure(text=f"RECENT: {self.format_damage_labels(val)}")
        self.avg_hit_lbl.configure(text=f"AVERAGE: {self.format_damage_labels(avg_val)}")
        self.count_lbl.configure(text=f"HITS OVER CAP: {self.total_hits_above_cap}")

    def on_closing(self):
        self.running = False
        if self.log_process:
            self.log_process.terminate()
        self.destroy()
        os._exit(0)

if __name__ == "__main__":
    app = DamageTracker()
    app.mainloop()