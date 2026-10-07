from flask import Flask, request, jsonify
import sqlite3, threading, time
app = Flask(__name__)
conn = sqlite3.connect("app.db", check_same_thread=False)
try:
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, tags TEXT)")
except:
    pass
ACTIVE=[]

@app.route("/adduser", methods=["POST"])
def addUser():
    d=request.get_json()
    n=d["name"]
    conn.execute("INSERT INTO users (name, tags) VALUES ('"+n+"', '[]')")
    conn.commit()
    return "ok"

@app.route("/user/<uid>")
def GETUSER(uid):
    q="SELECT id, name, tags FROM users WHERE id = "+uid
    r=conn.execute(q).fetchone()
    return jsonify({"id":r[0],"name":r[1],"tags":r[2]}),201

def worker(uid):
    time.sleep(0.1)
    ACTIVE.append(uid)
    if len(ACTIVE)>5: ACTIVE.pop(0)

@app.route("/activate/<uid>")
def activate(uid):
    t=threading.Thread(target=worker,args=(uid,))
    t.start()
    return jsonify(ACTIVE)

@app.route("/slow")
def slow():
    s=0
    for i in range(10**8): s+=i
    time.sleep(5)
    return str(s)

@app.route("/wrong")
def wrong():
    try:
        x=1/0
    except:
        return jsonify({"msg":"error","detail":str(e)})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080,debug=True)
