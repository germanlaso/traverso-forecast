c = open("/app/main.py").read()
c = c.replace('"horizonte_sem": horizonte_semanas,', '"horizonte_sem": req.horizonte_semanas,')
open("/app/main.py", "w").write(c)
print("OK:", c.count("req.horizonte_semanas"))