# test_porcupine.py
import os, sys
try:
    import ultron.config  # triggers load_dotenv fallback when python-dotenv missing
except Exception:
    pass

try:
    import pvporcupine
except Exception as e:
    print("Import pvporcupine FAILED:", e)
    sys.exit(2)

print("pvporcupine imported. version:", getattr(pvporcupine, "__version__", "unknown"))
print("Python:", sys.version)
print("Platform:", sys.platform, os.name, sys.maxsize.bit_length())

KEY = os.getenv("PORCUPINE_ACCESS_KEY", "")
print("PORCUPINE_ACCESS_KEY set:", bool(KEY), "len=", len(KEY or ""))

# Try builtin keyword (should not require custom .ppn)
try:
    p = pvporcupine.create(access_key=KEY or None, keywords=["porcupine"])
    print("Created Porcupine (builtin). sample_rate:", p.sample_rate, "frame_length:", p.frame_length)
    p.delete()
except Exception as e:
    print("Failed to create Porcupine (builtin):", repr(e))

# If you have a custom .ppn file, test it too (replace path if needed)
ppn = r"D:\UAssistent2\vassitry\models\ultron_win.ppn"
if os.path.exists(ppn):
    try:
        print("Trying custom model:", ppn)
        p2 = pvporcupine.create(access_key=KEY or None, keyword_paths=[ppn])
        print("Created Porcupine (custom). sample_rate:", p2.sample_rate, "frame_length:", p2.frame_length)
        p2.delete()
    except Exception as e:
        print("Failed to create Porcupine (custom):", repr(e))
else:
    print("No custom .ppn at:", ppn)