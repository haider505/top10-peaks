# -*- coding: utf-8 -*-
"""
يبني تطبيق أندرويد للعبة من index.html في جذر المشروع.

الخطوات:
  1. تنزيل Tailwind وخطوط Cairo و Readex Pro مرة واحدة إلى android/vendor/
  2. نسخ index.html إلى assets/ بعد استبدال روابط الإنترنت بالنسخ المحلية
     وإضافة طبقة صغيرة خاصة بالتطبيق (الحافظة، زر الرجوع، إخفاء النافذة المستقلة)
  3. إنشاء مفتاح التوقيع في android/keystore/ إن لم يوجد
  4. gradlew assembleRelease ثم نسخ الملف إلى dist/top10-peaks.apk

الاستخدام:
  python android/build_apk.py                  # بناء كامل
  python android/build_apk.py --sync-only      # تحديث assets/ فقط
  python android/build_apk.py --refresh-vendor # إعادة تنزيل الخطوط و Tailwind
"""
import datetime, glob, io, os, re, secrets, shutil, subprocess, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ANDROID = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ANDROID)
VENDOR = os.path.join(ANDROID, "vendor")
ASSETS = os.path.join(ANDROID, "app", "src", "main", "assets")
KEYSTORE_DIR = os.path.join(ANDROID, "keystore")
DIST_APK = os.path.join(ROOT, "dist", "top10-peaks.apk")

TAILWIND_VERSION = "3.4.17"
TAILWIND_URL = "https://cdn.tailwindcss.com/" + TAILWIND_VERSION
TAILWIND_FILE = "tailwind-%s.js" % TAILWIND_VERSION
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Readex+Pro:wght@300;400;500;600;700"
             "&family=Cairo:wght@400;600;700;900&display=swap")
# Google Fonts يرسل woff2 مقسّماً حسب الحروف (عربي/لاتيني) فقط للمتصفحات الحديثة.
BROWSER_UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")

# ما يُستبدل في index.html — كل نمط يجب أن يطابق مرة واحدة بالضبط.
REPLACEMENTS = [
    (r'<script src="https://cdn\.tailwindcss\.com/[^"]*"></script>',
     '<script src="vendor/%s"></script>' % TAILWIND_FILE),
    (r'<link rel="preconnect" href="https://fonts\.googleapis\.com">\n', ""),
    (r'<link rel="preconnect" href="https://fonts\.gstatic\.com" crossorigin>\n', ""),
    (r'<link href="https://fonts\.googleapis\.com/css2\?[^"]*" rel="stylesheet">',
     '<link href="vendor/fonts.css" rel="stylesheet">'),
]

APP_SHIM = """<!-- ===== طبقة تطبيق أندرويد (يضيفها android/build_apk.py) ===== -->
<style>
  /* window.open لا يعمل داخل التطبيق؛ نمط المقدم المدمج يبقى متاحاً */
  #btnOpenHostWin,#btnHostWin2{ display:none !important; }
</style>
<script>
window.TOP10_APP = true;
(function(){
  if(!window.AndroidApp) return;
  var clip = { writeText: function(t){
    try{ AndroidApp.copy(String(t)); return Promise.resolve(); }
    catch(e){ return Promise.reject(e); }
  }};
  try{ Object.defineProperty(navigator, "clipboard", { value: clip, configurable: true }); }
  catch(e){ try{ navigator.clipboard.writeText = clip.writeText; }catch(_){} }

  /* أشرطة النظام تتبع الوضع الليلي: نراقب الصنف dark على <html> */
  var root = document.documentElement, last = null;
  function reportTheme(){
    var dark = root.classList.contains("dark");
    if(dark !== last){ last = dark; try{ AndroidApp.setDark(dark); }catch(_){} }
  }
  reportTheme();
  new MutationObserver(reportTheme).observe(root, { attributes: true, attributeFilter: ["class"] });
})();
/* يستدعيه زر الرجوع: يغلق ما هو مفتوح ويعيد true، أو false إن لم يكن شيء مفتوحاً */
window.__top10Back = function(){
  function esc(){ document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); }
  var drawer = document.getElementById("drawer");
  if(drawer && drawer.classList.contains("open")){ esc(); return true; }
  var open = document.querySelectorAll(".modal.open");
  if(open.length){
    var m = open[open.length - 1];
    if(m.id === "qm") esc(); else m.classList.remove("open");
    return true;
  }
  if(typeof S !== "undefined" && S.hintMode){ esc(); return true; }
  return false;
};
</script>
"""

EXTERNAL_REF = re.compile(r"""(?:\b(?:src|href)\s*=\s*["']|url\(\s*["']?)https?://""", re.I)


def fetch(url, ua=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua or BROWSER_UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def ensure_vendor(refresh=False):
    fonts_dir = os.path.join(VENDOR, "fonts")
    tw = os.path.join(VENDOR, TAILWIND_FILE)
    css_out = os.path.join(VENDOR, "fonts.css")
    if refresh and os.path.isdir(VENDOR):
        shutil.rmtree(VENDOR)
    os.makedirs(fonts_dir, exist_ok=True)

    if not os.path.exists(tw):
        print("  downloading Tailwind", TAILWIND_VERSION)
        data = fetch(TAILWIND_URL)
        if len(data) < 100000:
            sys.exit("Tailwind download looks wrong (%d bytes)" % len(data))
        io.open(tw, "wb").write(data)

    if not os.path.exists(css_out):
        print("  downloading fonts CSS")
        css = fetch(FONTS_URL).decode("utf-8")
        urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css)))
        if not urls:
            sys.exit("No woff2 fonts found in Google Fonts CSS")
        for u in urls:
            name = u.rsplit("/", 1)[1]
            dest = os.path.join(fonts_dir, name)
            if not os.path.exists(dest):
                io.open(dest, "wb").write(fetch(u))
            css = css.replace(u, "fonts/" + name)
        io.open(css_out, "w", encoding="utf-8").write(css)
        print("  fonts: %d files" % len(urls))


def sync_assets():
    src = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    for pattern, repl in REPLACEMENTS:
        src, n = re.subn(pattern, lambda m: repl, src, count=1)
        if n != 1:
            sys.exit("index.html changed: pattern not found -> %s" % pattern)
    if src.count("</head>") != 1:
        sys.exit("index.html: expected exactly one </head>")
    src = src.replace("</head>", APP_SHIM + "</head>", 1)

    css = io.open(os.path.join(VENDOR, "fonts.css"), encoding="utf-8").read()
    for label, text in (("index.html", src), ("fonts.css", css)):
        hit = EXTERNAL_REF.search(text)
        if hit:
            line = text.count("\n", 0, hit.start()) + 1
            sys.exit("%s still loads from the internet (line %d)" % (label, line))

    if os.path.isdir(ASSETS):
        shutil.rmtree(ASSETS)
    shutil.copytree(VENDOR, os.path.join(ASSETS, "vendor"))
    io.open(os.path.join(ASSETS, "index.html"), "w", encoding="utf-8", newline="\n").write(src)
    total = sum(os.path.getsize(p) for p in glob.glob(os.path.join(ASSETS, "**", "*"), recursive=True)
                if os.path.isfile(p))
    print("  assets ready: %.1f MB (offline, no external URLs)" % (total / 1e6))


def find_java_home():
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(os.environ["JAVA_HOME"])
    for pattern in (r"C:\Program Files\Java\jdk-*", r"C:\Program Files\Eclipse Adoptium\jdk-*",
                    r"C:\Program Files\Microsoft\jdk-*", r"C:\Program Files\Android\Android Studio\jbr"):
        candidates += sorted(glob.glob(pattern), reverse=True)
    for c in candidates:
        m = re.search(r"jdk-?(\d+)", os.path.basename(c))
        if m and int(m.group(1)) < 17:
            continue
        exe = os.path.join(c, "bin", "java.exe" if os.name == "nt" else "java")
        if os.path.exists(exe):
            return c
    sys.exit("JDK 17+ not found; set JAVA_HOME")


def read_sdk_dir():
    lp = os.path.join(ANDROID, "local.properties")
    if os.path.exists(lp):
        for line in io.open(lp, encoding="utf-8"):
            if line.startswith("sdk.dir="):
                return line.split("=", 1)[1].strip().replace("\\:", ":").replace("\\\\", "\\")
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        sys.exit("Android SDK not found: create android/local.properties with sdk.dir=... or set ANDROID_HOME")
    io.open(lp, "w", encoding="utf-8").write("sdk.dir=" + sdk.replace("\\", "\\\\").replace(":", "\\:") + "\n")
    return sdk


def ensure_keystore(java_home):
    props = os.path.join(KEYSTORE_DIR, "keystore.properties")
    if os.path.exists(props):
        return
    os.makedirs(KEYSTORE_DIR, exist_ok=True)
    jks = os.path.join(KEYSTORE_DIR, "top10-peaks.jks")
    if os.path.exists(jks):
        sys.exit("keystore exists but keystore.properties is missing: " + jks)
    password = secrets.token_urlsafe(18)
    keytool = os.path.join(java_home, "bin", "keytool")
    subprocess.run([keytool, "-genkeypair", "-keystore", jks, "-storetype", "PKCS12",
                    "-alias", "top10peaks", "-keyalg", "RSA", "-keysize", "2048",
                    "-validity", "10000", "-dname", "CN=Top10 Peaks, O=haider505",
                    "-storepass", password, "-keypass", password],
                   check=True, stdout=subprocess.DEVNULL)
    io.open(props, "w", encoding="utf-8").write(
        "storeFile=top10-peaks.jks\nstorePassword=%s\nkeyAlias=top10peaks\nkeyPassword=%s\n"
        % (password, password))
    print("  NEW signing key created in android/keystore/ -- back it up!")
    print("  Without it, future versions cannot be installed over this one.")


def build_apk():
    java_home = find_java_home()
    sdk_dir = read_sdk_dir()
    ensure_keystore(java_home)

    env = dict(os.environ)
    env["JAVA_HOME"] = java_home
    env.setdefault("GRADLE_USER_HOME", os.path.join(sdk_dir, ".gradle"))   # بعيداً عن C: الممتلئ

    now = datetime.datetime.now()
    version_code = int((now - datetime.datetime(2026, 1, 1)).total_seconds() // 60)
    version_name = now.strftime("%Y.%m.%d")
    gradlew = os.path.join(ANDROID, "gradlew.bat" if os.name == "nt" else "gradlew")
    print("  gradle assembleRelease (version %s, code %d)" % (version_name, version_code))
    subprocess.run([gradlew, "--no-daemon", "assembleRelease",
                    "-PappVersionCode=%d" % version_code, "-PappVersionName=%s" % version_name],
                   cwd=ANDROID, env=env, check=True)

    built = os.path.join(ANDROID, "app", "build", "outputs", "apk", "release", "app-release.apk")
    if not os.path.exists(built):
        sys.exit("APK not found (is the keystore set up?): " + built)
    os.makedirs(os.path.dirname(DIST_APK), exist_ok=True)
    shutil.copyfile(built, DIST_APK)
    print("  APK: %s (%.1f MB)" % (DIST_APK, os.path.getsize(DIST_APK) / 1e6))


def main():
    print("vendor:")
    ensure_vendor(refresh="--refresh-vendor" in sys.argv)
    print("assets:")
    sync_assets()
    if "--sync-only" in sys.argv:
        return
    print("build:")
    build_apk()
    print("done.")


if __name__ == "__main__":
    main()
