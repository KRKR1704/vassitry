import pyttsx3
import platform

print("System:", platform.system())

try:
    engine = pyttsx3.init(driverName="sapi5" if platform.system() == "Windows" else None)
except Exception as e:
    print("Init failed:", e)
    exit(1)

voices = engine.getProperty("voices")
print("Voices found:", len(voices))
for v in voices:
    print(f"- id='{v.id}' name='{v.name}' lang='{getattr(v, 'languages', '')}'")

print("Trying to speak test line...")
engine.say("Hello, this is a speech test from Ultron.")
engine.runAndWait()
print("Done.")
