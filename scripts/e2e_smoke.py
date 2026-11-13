"""End-to-end smoke test: runs the FULL user journey through the running frontend proxy.

Usage:  python3 scripts/e2e_smoke.py [frontend_base_url]
Default base: http://127.0.0.1:3000  (Next.js proxies /backend -> FastAPI)
Requires: backend running (docker compose up or locally).
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000") + "/backend/api/v1"
ok_count = 0


def ok(cond, label):
    global ok_count
    print(("PASS" if cond else "FAIL"), "-", label)
    if cond:
        ok_count += 1
    else:
        sys.exit(f"FAILED at: {label}")


def req(path, method="GET", data=None, token=None, raw_body=None, headers=None):
    h = dict(headers or {})
    if token:
        h["authorization"] = f"Bearer {token}"
    body = raw_body if raw_body is not None else (json.dumps(data).encode() if data is not None else None)
    if data is not None:
        h["content-type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            if "json" in resp.headers.get("content-type", ""):
                return resp.status, json.loads(resp.read())
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None


def main():
    # sample book is generated with the same factory the tests use
    sys.path.insert(0, "backend")
    from tests.pdf_factory import make_sample_book

    email = f"e2e-{int(time.time())}@lingora.uz"
    st, reg = req("/auth/register", "POST", {"email": email, "password": "Parol12345", "full_name": "E2E"})
    ok(st == 201, "register")
    tok = reg["access_token"]

    boundary = "----lingorae2e"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nE2E Book\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"consent\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"e2e.pdf\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + make_sample_book() + f"\r\n--{boundary}--\r\n".encode()
    st, book = req("/books/upload", "POST", token=tok, raw_body=body,
                   headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    ok(st == 201, "upload")
    bid = book["id"]

    job = None
    for _ in range(120):
        st, job = req(f"/books/{bid}/status", token=tok)
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    ok(job and job["status"] == "completed", "AI analysis pipeline completed")

    st, struct = req(f"/books/{bid}/structure", token=tok)
    ok(st == 200 and struct["coverage"]["exercises"] >= 3, f"structure detected: {struct['coverage']}")
    l1, l2 = struct["lessons"][0], struct["lessons"][1]

    st, exs = req(f"/lessons/{l1['id']}/exercises", token=tok)
    fill = next(e for e in exs if e["exercise_type"] == "fill_blank")
    answers = []
    for q in fill["questions"]:
        val = "goes" if "She" in q["prompt"] else ("play" if "They" in q["prompt"] else "does")
        answers.append({"question_id": q["id"], "content": {"blanks": {"b1": val}}})
    req(f"/exercises/{fill['id']}/answers", "PUT", {"answers": answers}, token=tok)
    st, saved = req(f"/exercises/{fill['id']}/answers", token=tok)
    ok(len(saved) == len(answers), "answers autosave + resume")
    st, res = req(f"/exercises/{fill['id']}/check", "POST", token=tok)
    ok(res["percent"] == 100.0, f"graded from book key: {res['percent']}%")

    st, sess = req(f"/vocabulary/sessions?lesson_id={l1['id']}&kind=lesson_gate", "POST", token=tok)
    ok(st == 201, f"vocab session ({len(sess['items'])} items)")
    words = {w["id"]: w for w in req(f"/books/{bid}/vocabulary", token=tok)[1]}

    def solve(item):
        # Session items expose their word_id, so use that rather than guessing
        # from prompts (which may be translations, audio or a blank sentence).
        word = words[item["word_id"]]
        if item["type"] == "choice_en_uz":
            return word["translation_uz"].split(",")[0].strip()
        if item["type"] == "written_en_uz":
            return word["translation_uz"]
        return word["term"]

    for _round in range(2):
        seen = {i["item_id"]: i for i in sess["items"]}
        order = [i["item_id"] for i in sess["items"]]
        idx, answered, any_wrong = 0, set(), False
        while idx < len(order):
            iid = order[idx]; item = seen[iid]; idx += 1
            if iid in answered:
                continue
            st, r = req(f"/vocabulary/sessions/{sess['id']}/answer", "POST",
                        {"item_id": iid, "response": solve(item) or "x"}, token=tok)
            answered.add(iid)
            if not r["correct"]:
                any_wrong = True
                st, s2 = req(f"/vocabulary/sessions/{sess['id']}", token=tok)
                for i in s2["items"]:
                    if i["item_id"] not in seen:
                        seen[i["item_id"]] = i
                        order.append(i["item_id"])
        if not any_wrong:
            break
        st, sess = req(f"/vocabulary/sessions?lesson_id={l1['id']}&kind=lesson_gate", "POST", token=tok)

    st, fin = req(f"/vocabulary/sessions/{sess['id']}/complete", "POST", token=tok)
    ok(fin["passed"] and fin["gate_opened"], f"vocab gate passed ({fin['score']}%) — lesson 2 unlocked")

    st, struct2 = req(f"/books/{bid}/structure", token=tok)
    ok(struct2["lessons_progress"][l2["id"]]["locked"] is False, "lesson gating updated")

    st, dash = req("/progress/dashboard", token=tok)
    ok(dash["exercises_checked"] >= 1 and dash["vocab_words_total"] > 0, "dashboard stats")

    st, conv = req("/tutor/conversations", "POST", {"book_id": bid, "lesson_id": l1["id"]}, token=tok)
    st, msg = req(f"/tutor/conversations/{conv['id']}/messages", "POST", {"content": "salom"}, token=tok)
    ok(st == 503 and msg["error"]["code"] == "AI_NOT_CONFIGURED", "AI honestly reports not configured")

    st, reg2 = req("/auth/register", "POST", {"email": f"n-{int(time.time())}@x.uz", "password": "Parol12345"})
    st, bl = req("/books", token=reg2["access_token"])
    ok(all(b["id"] != bid for b in bl), "privacy: another user sees nothing")
    st, _f = req(f"/books/{bid}/file", token=reg2["access_token"])
    ok(st == 404, "privacy: PDF download blocked for others")

    print(f"\n=== E2E SMOKE: {ok_count} checks passed ===")


if __name__ == "__main__":
    main()
