# AG VIDEO CUTTER — বাংলা সেটআপ

## কী করে
- ওয়েবসাইটে ভিডিও আপলোড করে FFmpeg দিয়ে ৪টি সমান-সময়ের অংশ তৈরি করে।
- আপলোড ৪ MiB chunk-এ হয়, যাতে একটি বিশাল HTTP request এড়ানো যায়।
- Upload/processing progress দেখায় এবং চারটি আলাদা MP4 download link দেয়।
- Frontend ফাইল আলাদা: `index.html`, `style.css`, `app.js`; backend `server.py`।

## গুরুত্বপূর্ণ বাস্তব সীমাবদ্ধতা
**Render Free-তে 500 MB–2 GB ভিডিও নির্ভরযোগ্যভাবে প্রক্রিয়া হবে—এমন নিশ্চয়তা নেই।** Chunked upload একক request ছোট করে, কিন্তু মোট upload, disk, RAM, CPU, process/runtime, free-service sleep এবং temporary filesystem-এর সীমা দূর করে না। 2 GB source-এর পাশাপাশি output files-এর জন্যও একাধিক GB storage দরকার হতে পারে। Free instance restart/deploy হলে `/tmp`-এর job files হারিয়ে যেতে পারে। বড় ভিডিওর জন্য পর্যাপ্ত RAM/CPU এবং persistent disk-সহ paid VPS/host বা আপনার নিজস্ব কম্পিউটার-সার্ভার অধিক বাস্তবসম্মত। Render-এর বর্তমান সীমা deploy করার আগে Render docs-এ যাচাই করুন।

এই demo backend প্রতি ভিডিওকে পুরোপুরি re-encode করে; এটি CPU-intensive। 2 GB ভিডিওতে free host timeout/OOM/storage error হওয়া স্বাভাবিক। `MAX_UPLOAD_BYTES=2147483648` কেবল app-এর অনুমোদিত সীমা, host capability-এর গ্যারান্টি নয়। পাবলিক সাইটে authentication, quotas, rate limiting, cleanup job, persistent storage এবং abuse protection যোগ না করে ব্যবহার করবেন না।

## Android / Termux-এ লোকালি চালানো
1. ফোল্ডারের সব ফাইল Termux-এ রাখুন, তারপর:
   ```bash
   pkg update
   pkg install python ffmpeg -y
   python -m pip install -r requirements.txt
   ```
2. চালান:
   ```bash
   cd ~/AG-VIDEO-CUTTER-WEBSITE
   python server.py
   ```
3. ফোনের browser-এ `http://127.0.0.1:10000` খুলুন।
4. ফোনে বড় ভিডিও প্রসেস করতে পর্যাপ্ত খালি storage লাগবে। 2 GB source-এর জন্য source + output + temporary files মিলে কয়েক GB বা তার বেশি লাগতে পারে; low-RAM ফোনে বড় ভিডিও ব্যর্থ হতে পারে।

## GitHub + Render deployment
1. এই project-এর সব ফাইল GitHub repository-তে upload করুন।
2. Render Dashboard → New → Blueprint (অথবা New Web Service) → GitHub repository নির্বাচন করুন।
3. Blueprint ব্যবহার করলে `render.yaml` পড়ে service configure হবে। Manual service হলে:
   - Build command: `bash build.sh`
   - Start command: `gunicorn server:app --workers 1 --threads 4 --timeout 3600 --bind 0.0.0.0:$PORT`
4. Deploy-এর পর `https://YOUR-SERVICE.onrender.com/api/health` খুলে `status: running` এবং `ffmpeg: true` দেখুন।
5. তারপর homepage-এ ছোট test MP4 দিয়ে পরীক্ষা করুন। বড় ভিডিও দিয়ে শুরু করবেন না।

## API endpoints
- `GET /api/health`
- `POST /api/start`
- `POST /api/upload/<job_id>/<chunk_index>` (multipart form field `chunk`)
- `POST /api/upload/<job_id>/complete`
- `GET /api/status/<job_id>`
- `GET /api/download/<job_id>/part_1.mp4` … `part_4.mp4`

## Notes
- Output clips are re-encoded to H.264/AAC MP4 for broad compatibility.
- Splits are based on total container duration / 4. Variable frame rate and unusual containers may produce slight boundary differences.
- No file is automatically uploaded to Google Drive or another storage provider.
- Do not upload private/sensitive videos to an untrusted public server.
