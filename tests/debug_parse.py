from ultron.nlp.intent import parse_intent

cases = [
    "launch spotify",
    "connect to 'MyNetwork'",
    "unmute",
    "unmute volume",
]

for c in cases:
    ir = parse_intent(c)
    print(f"INPUT: {c!r} -> intent={ir.intent!r}, entity={ir.entity!r}, slots={ir.slots!r}")
