c = open("/app/mrp.py").read()
old = "s = str(s).lower().strip()"
new = "s = str(s).lower().strip().replace('\\n', ' ')"
c = c.replace(old, new)
open("/app/mrp.py", "w").write(c)
print("OK:", c.count("replace('\\\\n'"))
