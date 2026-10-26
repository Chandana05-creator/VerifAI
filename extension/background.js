// VerifAI extension — background service worker: adds the right-click menu items.
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "verifai-selection", title: "Verify “%s” with VerifAI", contexts: ["selection"] });
    chrome.contextMenus.create({ id: "verifai-page", title: "Verify this page with VerifAI", contexts: ["page"] });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const p = new URLSearchParams();
  const pageUrl = info.pageUrl || (tab && tab.url) || "";
  if (info.menuItemId === "verifai-selection") {
    p.set("text", (info.selectionText || "").slice(0, 3000));
    p.set("auto", "text");
  } else {
    p.set("auto", "page");
  }
  p.set("pageUrl", pageUrl);
  chrome.windows.create({ url: chrome.runtime.getURL("popup.html?" + p.toString()), type: "popup", width: 470, height: 720 });
});
