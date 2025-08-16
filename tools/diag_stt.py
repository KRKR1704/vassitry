import speech_recognition as sr

print("Listing microphones:")
for i, name in enumerate(sr.Microphone.list_microphone_names() or []):
    print(f"{i}: {name}")

r = sr.Recognizer()
device_index = None  # try default first

try:
    with sr.Microphone(device_index=device_index) as source:
        print("\nSay something after the beep...")
        r.adjust_for_ambient_noise(source, duration=0.5)
        print("Listening...")
        audio = r.listen(source, timeout=8, phrase_time_limit=10)
    print("Recognizing...")
    text = r.recognize_google(audio)
    print("You said:", text)
except sr.WaitTimeoutError:
    print("Timeout: no speech detected.")
except sr.UnknownValueError:
    print("Could not understand audio.")
except Exception as e:
    print("Error:", e)
