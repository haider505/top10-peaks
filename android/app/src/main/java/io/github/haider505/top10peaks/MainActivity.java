package io.github.haider505.top10peaks;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.webkit.WebViewAssetLoader;

/**
 * غلاف أندرويد للعبة توب تن بيكس: يعرض نسخة اللعبة المدمجة في assets/
 * عبر WebView، فتعمل بلا إنترنت. الصفحة تُخدَم من نطاق https محلي
 * (appassets.androidplatform.net) حتى يعمل localStorage والحافظة كما في المتصفح.
 */
public class MainActivity extends Activity {

    private static final String ASSET_HOST = "appassets.androidplatform.net";
    private static final String START_URL = "https://" + ASSET_HOST + "/assets/index.html";
    private static final int FILE_CHOOSER_REQUEST = 1001;
    private static final int BG_COLOR = 0xFFEDF1F8;   // --bg في اللعبة
    private static final int BG_DARK = 0xFF0F1524;    // --bg في الوضع الليلي
    private static final long EXIT_WINDOW_MS = 2000;
    private static final String PREFS = "app";
    private static final String PREF_DARK = "dark";

    private FrameLayout root;
    private WebView webView;
    private ValueCallback<Uri[]> pendingFileCallback;
    private long lastBackPress;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // اللعبة تُعرض أمام مجموعة؛ لا نريد أن تنطفئ الشاشة أثناء الجولة.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        webView = new WebView(this);
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        fitInsideSystemBars(root);
        // آخر وضع اختاره اللاعب، حتى لا تومض الواجهة الفاتحة قبل تحميل الصفحة.
        applySystemBarTheme(getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(PREF_DARK, false));

        final WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .setDomain(ASSET_HOST)
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);                    // localStorage للأسئلة المضافة
        s.setMediaPlaybackRequiresUserGesture(false);    // أصوات AudioContext
        s.setAllowFileAccess(false);
        s.setSupportMultipleWindows(false);

        webView.addJavascriptInterface(new AppBridge(), "AndroidApp");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri url = request.getUrl();
                if (ASSET_HOST.equals(url.getHost())) return false;
                // أي رابط خارجي يُفتح في المتصفح بدل أن يحلّ محل اللعبة.
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, url));
                } catch (ActivityNotFoundException ignored) {
                }
                return true;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingFileCallback != null) pendingFileCallback.onReceiveValue(null);
                pendingFileCallback = callback;
                // كثير من مديري الملفات لا يعرّفون .json بنوع MIME صحيح، فنقبل الكل
                // ونترك للعبة رفض الملف غير الصالح كما تفعل في المتصفح.
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(pick, getString(R.string.pick_file)),
                            FILE_CHOOSER_REQUEST);
                } catch (ActivityNotFoundException e) {
                    pendingFileCallback = null;
                    return false;
                }
                return true;
            }
        });

        if (savedInstanceState == null || webView.restoreState(savedInstanceState) == null) {
            webView.loadUrl(START_URL);
        }
    }

    /** على Android 11+ نرسم خلف الأشرطة بأنفسنا ونترك هامشاً بقدرها وبقدر لوحة المفاتيح. */
    private void fitInsideSystemBars(FrameLayout root) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return;   // الأقدم يضبطها النظام
        getWindow().setDecorFitsSystemWindows(false);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            android.graphics.Insets ime = insets.getInsets(WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            return WindowInsets.CONSUMED;
        });
    }

    /** يلوّن الخلفية وأشرطة النظام بلون اللعبة، وأيقونات الأشرطة داكنة على الفاتح والعكس. */
    @SuppressWarnings("deprecation")
    private void applySystemBarTheme(boolean dark) {
        int color = dark ? BG_DARK : BG_COLOR;
        root.setBackgroundColor(color);
        if (webView != null) webView.setBackgroundColor(color);
        Window window = getWindow();
        window.setStatusBarColor(color);       // يتجاهله Android 15+ (الأشرطة شفافة فوق root)
        window.setNavigationBarColor(color);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = window.getInsetsController();
            if (c != null) {
                int mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                c.setSystemBarsAppearance(dark ? 0 : mask, mask);
            }
        } else {
            View decor = window.getDecorView();
            int light = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) light |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            int flags = decor.getSystemUiVisibility();
            decor.setSystemUiVisibility(dark ? (flags & ~light) : (flags | light));
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (pendingFileCallback != null) {
                pendingFileCallback.onReceiveValue(
                        WebChromeClient.FileChooserParams.parseResult(resultCode, data));
                pendingFileCallback = null;
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /** الرجوع يغلق النافذة المفتوحة في اللعبة أولاً، ثم يطلب ضغطة ثانية للخروج. */
    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        webView.evaluateJavascript(
                "window.__top10Back ? window.__top10Back() : false",
                closed -> {
                    if ("true".equals(closed)) return;
                    long now = System.currentTimeMillis();
                    if (now - lastBackPress < EXIT_WINDOW_MS) {
                        finish();
                    } else {
                        lastBackPress = now;
                        Toast.makeText(this, R.string.press_again_to_exit, Toast.LENGTH_SHORT).show();
                    }
                });
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
    }

    @Override
    protected void onPause() {
        webView.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    /** جسر صغير تستدعيه الصفحة: النسخ إلى الحافظة لا يعمل دائماً من داخل WebView. */
    private final class AppBridge {
        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("top10-peaks", text));
        }

        /** تستدعيه الصفحة كلما تبدّل الوضع الليلي. */
        @JavascriptInterface
        public void setDark(boolean dark) {
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean(PREF_DARK, dark).apply();
            runOnUiThread(() -> {
                if (root != null) applySystemBarTheme(dark);
            });
        }
    }
}
