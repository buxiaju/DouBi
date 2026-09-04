package com.doubi.android.core.sniffer

import android.content.Context
import android.webkit.WebView

/**
 * 阶段 11 v0.5.1：[WebViewHolder] 创建 WebView 的工厂接口。
 *
 * **目的**：v0.5.0 阶段 10 的 `WebViewHolder` 用 `by lazy` 直接 `WebView(context).apply { ... }`，
 * 单元测试没法替换 WebView 创建逻辑（WebView 是 Android framework 真实组件，没法 mockk）。
 * v0.5.1 抽出 [WebViewFactory] interface，[WebViewHolder] 依赖工厂不直接 `new WebView()`，
 * 单元测试里用 mockk 工厂验证"创建时机 / 复用 / release 触发 destroy"等契约。
 *
 * **v0.5.1 范围**：
 * - `fun interface` 只有一个 `create(context)` 方法
 * - 默认实现 [DefaultWebViewFactory] 走 v0.5.0 阶段 10 写死的 0 size + GONE + JS enabled 等配置
 * - SnifferModule 用 `@Binds` 把 `DefaultWebViewFactory` 绑到 `WebViewFactory`
 *
 * **风险**：抽出后 WebView 创建逻辑挪到独立类，单测覆盖率上升，但单测不能覆盖
 * WebView 自身的 0 size / GONE / JS enabled 配置（这些是 Android framework 行为，
 * 需要 Robolectric / 真机验证）。v0.5.1+ 走 instrumented test 覆盖。
 */
fun interface WebViewFactory {
    /**
     * 创建一个新 WebView。
     *
     * @param context Application context（Hilt 注入 `@ApplicationContext`）
     * @return 配置好的 WebView 实例（0 size + GONE + 嗅探用的 JS / DOM / cache 设置）
     */
    fun create(context: Context): WebView
}
