"""Desktop notifications through freedesktop and Windows toast."""
import os
import subprocess


def notify(message, title="Dracaena", urgency="normal"):
    if os.name == "nt":
        from windows_toasts import Toast, WindowsToaster
        toaster = WindowsToaster("Dracaena")
        toast = Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
        return
    subprocess.run(["notify-send", "--app-name=Dracaena", "--urgency=" + urgency, "--", title, message],
                   check=True, timeout=5)
