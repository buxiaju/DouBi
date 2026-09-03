package com.doubi.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.doubi.android.R

/**
 * 阶段 6 设置 tab。1:1 对拍桌面版 `src/doubi/ui/pages/settings.py:SettingsPage`。
 *
 * 设计：LazyColumn 渲染若干 SectionCard，每组若干 Row。改字段调 ViewModel.onFieldChanged
 * → 写 DataStore → reactive 回写到 observe() → UI 立刻更新。**立即生效** vs 桌面版的
 * 「需重启」差异见 SettingsViewModel 注释。
 *
 * v0.1 范围（按用户规模简化）：
 * - 输出（outputRoot / outputDirTemplate / filenameTemplate）
 * - 画质 / 容器（maxQuality / container）+ 并发数
 * - 附加（缩略图 / 字幕 / 续传）
 * - 网络（proxy / rateLimit）
 * - 通知（notifyOnCompletion dropdown）
 *
 * 不做（v0.2.2 阶段 7 补）：
 * - 主题（theme 字段）—— Material 3 暂用系统亮/暗
 * - 通用嗅探全字段（sniffHeadless / sniffUserAgent / sniffAutoPlay）—— Android 端
 *   sniff v0.2 阶段 7 才有完整实现
 * - aria2 引擎字段（v0.1 不支持 aria2 引擎）
 */
@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val savedMsg = stringResource(R.string.settings_saved, "%s")

    LaunchedEffect(Unit) {
        viewModel.events.collect { ev ->
            when (ev) {
                is SettingsViewModel.Event.Saved -> {
                    snackbarHostState.showSnackbar(savedMsg.format(ev.key))
                    viewModel.onEventShown()
                }
                is SettingsViewModel.Event.Failure -> {
                    snackbarHostState.showSnackbar(savedMsg.format(ev.key + ": " + ev.error))
                    viewModel.onEventShown()
                }
                null -> Unit
            }
        }
    }

    val config = state.config
    val context = LocalContext.current
    val noAppMsg = stringResource(R.string.settings_no_app_to_open_dir)
    Box(modifier = modifier.fillMaxSize()) {
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            item { SectionHeader(stringResource(R.string.settings_section_general)) }
            item {
                ActionRow(
                    label = stringResource(R.string.settings_open_save_dir),
                    hint = stringResource(R.string.settings_open_save_dir_hint),
                    buttonText = stringResource(R.string.settings_open_save_dir),
                    onClick = {
                        // 阶段 9 v0.4.1：启动系统文件选择器让用户授权 DouBi 下载目录。
                        // ACTION_OPEN_DOCUMENT_TREE 是 Android 5+ 标准 API，无需权限。
                        // v0.4.1 简化版：只启动 intent，不处理 onActivityResult 拿 takePersistableUriPermission
                        // （v0.5.0+ 拓展 navigate）。即使用户没授权，下完文件后他能用系统文件管理器
                        // 浏览 /sdcard/Android/data/com.doubi.android/files/Downloads/ 也行。
                        val intent = android.content.Intent(
                            android.content.Intent.ACTION_OPEN_DOCUMENT_TREE,
                        ).apply {
                            flags = android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                        }
                        try {
                            context.startActivity(intent)
                        } catch (e: android.content.ActivityNotFoundException) {
                            android.widget.Toast.makeText(
                                context, noAppMsg, android.widget.Toast.LENGTH_SHORT,
                            ).show()
                        }
                    },
                )
            }

            item { SectionHeader(stringResource(R.string.settings_section_output)) }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_output_root),
                    value = config.outputRoot,
                    onValueChange = { viewModel.onFieldChanged("output_root", it.ifBlank { null }) },
                    hint = stringResource(R.string.settings_output_root_hint),
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_output_dir_template),
                    value = config.outputDirTemplate,
                    onValueChange = { viewModel.onFieldChanged("output_dir_template", it.ifBlank { null }) },
                    hint = stringResource(R.string.settings_output_dir_template_hint),
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_filename_template),
                    value = config.filenameTemplate,
                    onValueChange = { viewModel.onFieldChanged("filename_template", it.ifBlank { null }) },
                    hint = stringResource(R.string.settings_filename_template_hint),
                )
            }

            item { SectionHeader(stringResource(R.string.settings_section_quality)) }
            item {
                DropdownRow(
                    label = stringResource(R.string.settings_max_quality),
                    value = config.maxQuality,
                    options = listOf("best", "1080p", "720p", "480p", "360p", "240p", "audio"),
                    onValueChange = { viewModel.onFieldChanged("max_quality", it) },
                )
            }
            item {
                DropdownRow(
                    label = stringResource(R.string.settings_container),
                    value = config.container,
                    options = listOf("mp4", "mkv"),
                    onValueChange = { viewModel.onFieldChanged("container", it) },
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_concurrent_jobs),
                    value = config.concurrentJobs.toString(),
                    onValueChange = { v ->
                        val n = v.toIntOrNull() ?: return@TextFieldRow
                        viewModel.onFieldChanged("concurrent_jobs", n)
                    },
                    hint = stringResource(R.string.settings_concurrent_jobs_hint),
                    keyboardType = KeyboardType.Number,
                )
            }

            item { SectionHeader(stringResource(R.string.settings_section_options)) }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_write_thumbnail),
                    checked = config.writeThumbnail,
                    onCheckedChange = { viewModel.onFieldChanged("write_thumbnail", it) },
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_write_subtitles),
                    checked = config.writeSubtitles,
                    onCheckedChange = { viewModel.onFieldChanged("write_subtitles", it) },
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_resume),
                    checked = config.resume,
                    onCheckedChange = { viewModel.onFieldChanged("resume", it) },
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_prompt_before_download),
                    checked = config.promptBeforeDownload,
                    onCheckedChange = { viewModel.onFieldChanged("prompt_before_download", it) },
                )
            }

            item { SectionHeader(stringResource(R.string.settings_section_network)) }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_proxy),
                    value = config.proxy ?: "",
                    onValueChange = { viewModel.onFieldChanged("proxy", it.ifBlank { null }) },
                    hint = stringResource(R.string.settings_proxy_hint),
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_rate_limit),
                    value = config.rateLimit ?: "",
                    onValueChange = { viewModel.onFieldChanged("rate_limit", it.ifBlank { null }) },
                    hint = stringResource(R.string.settings_rate_limit_hint),
                )
            }

            item { SectionHeader(stringResource(R.string.settings_section_notify)) }
            item {
                DropdownRow(
                    label = stringResource(R.string.settings_notify_on_completion),
                    value = config.notifyOnCompletion,
                    options = listOf("success", "all", "summary"),
                    onValueChange = { viewModel.onFieldChanged("notify_on_completion", it) },
                )
            }

            // ---- 阶段 9 v0.4.1：主题切换 ----
            item { SectionHeader(stringResource(R.string.settings_section_theme)) }
            item {
                // 把显示文字提到 Composable 顶层（lambda 内不能调 stringResource）
                val themeSystemText = stringResource(R.string.settings_theme_system)
                val themeLightText = stringResource(R.string.settings_theme_light)
                val themeDarkText = stringResource(R.string.settings_theme_dark)
                DropdownRow(
                    label = stringResource(R.string.settings_theme),
                    value = themeDisplay(config.theme),
                    options = listOf(themeSystemText, themeLightText, themeDarkText),
                    onValueChange = { display ->
                        val key = when (display) {
                            themeLightText -> "default_light"
                            themeDarkText -> "default_dark"
                            else -> "system"
                        }
                        viewModel.onFieldChanged("theme", key)
                    },
                )
            }

            // ---- 阶段 9 v0.4.1：重复下载策略 ----
            item { SectionHeader(stringResource(R.string.settings_section_duplicate)) }
            item {
                val dupSkipText = stringResource(R.string.settings_duplicate_skip)
                val dupRedownloadText = stringResource(R.string.settings_duplicate_redownload)
                val dupAskText = stringResource(R.string.settings_duplicate_ask)
                DropdownRow(
                    label = stringResource(R.string.settings_duplicate_policy),
                    value = duplicateDisplay(config.duplicatePolicy),
                    options = listOf(dupSkipText, dupRedownloadText, dupAskText),
                    onValueChange = { display ->
                        val key = when (display) {
                            dupRedownloadText -> "redownload"
                            dupAskText -> "ask"
                            else -> "skip"
                        }
                        viewModel.onFieldChanged("duplicate_policy", key)
                    },
                )
            }

            // ---- 阶段 9 v0.4.1：附加 NFO / metadata.json / 弹幕 ----
            item { SectionHeader(stringResource(R.string.settings_section_attach_extra)) }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_write_nfo),
                    checked = config.writeNfo,
                    onCheckedChange = { viewModel.onFieldChanged("write_nfo", it) },
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_write_metadata_json),
                    checked = config.writeMetadataJson,
                    onCheckedChange = { viewModel.onFieldChanged("write_metadata_json", it) },
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_write_danmaku),
                    checked = config.writeDanmaku,
                    onCheckedChange = { viewModel.onFieldChanged("write_danmaku", it) },
                )
            }

            // ---- 阶段 9 v0.4.1：下载引擎（含 aria2 占位）----
            item { SectionHeader(stringResource(R.string.settings_engine)) }
            item {
                DropdownRow(
                    label = stringResource(R.string.settings_engine),
                    value = config.engine,
                    options = listOf("yt-dlp", "aria2"),
                    onValueChange = { viewModel.onFieldChanged("engine", it) },
                )
            }
            if (config.engine == "aria2") {
                item {
                    TextFieldRow(
                        label = stringResource(R.string.settings_aria2_rpc_url),
                        value = config.aria2RpcUrl,
                        onValueChange = { viewModel.onFieldChanged("aria2_rpc_url", it.ifBlank { null }) },
                        hint = stringResource(R.string.settings_aria2_rpc_url_hint),
                    )
                }
            }

            // ---- 阶段 9 v0.4.1：通用嗅探（5 字段）----
            item { SectionHeader(stringResource(R.string.settings_section_sniff)) }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_sniff_enabled),
                    checked = config.sniffEnabled,
                    onCheckedChange = { viewModel.onFieldChanged("sniff_enabled", it) },
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_sniff_duration_sec),
                    value = config.sniffDurationSec.toString(),
                    onValueChange = { v ->
                        val n = v.toIntOrNull() ?: return@TextFieldRow
                        viewModel.onFieldChanged("sniff_duration_sec", n)
                    },
                    hint = stringResource(R.string.settings_sniff_duration_sec_hint),
                    keyboardType = KeyboardType.Number,
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_sniff_headless),
                    checked = config.sniffHeadless,
                    onCheckedChange = { viewModel.onFieldChanged("sniff_headless", it) },
                )
            }
            item {
                TextFieldRow(
                    label = stringResource(R.string.settings_sniff_user_agent),
                    value = config.sniffUserAgent,
                    onValueChange = { viewModel.onFieldChanged("sniff_user_agent", it) },
                    hint = stringResource(R.string.settings_sniff_user_agent_hint),
                )
            }
            item {
                SwitchRow(
                    label = stringResource(R.string.settings_sniff_auto_play),
                    checked = config.sniffAutoPlay,
                    onCheckedChange = { viewModel.onFieldChanged("sniff_auto_play", it) },
                )
            }
        }

        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(16.dp),
        )
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(top = 4.dp, bottom = 4.dp),
    )
}

@Composable
private fun TextFieldRow(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    hint: String = "",
    keyboardType: KeyboardType = KeyboardType.Text,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        placeholder = if (hint.isNotBlank()) {
            { Text(hint, style = MaterialTheme.typography.bodySmall) }
        } else null,
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun SwitchRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            Switch(checked = checked, onCheckedChange = onCheckedChange)
        }
    }
}

@Composable
private fun DropdownRow(
    label: String,
    value: String,
    options: List<String>,
    onValueChange: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { expanded = true }) {
                Text(value)
            }
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
            ) {
                options.forEach { opt ->
                    DropdownMenuItem(
                        text = { Text(opt) },
                        onClick = {
                            onValueChange(opt)
                            expanded = false
                        },
                    )
                }
            }
        }
    }
}

/**
 * 阶段 9 v0.4.1 启用：「打开保存目录」按钮行。
 *
 * 跟 [SwitchRow] / [DropdownRow] 不一样：纯动作按钮，不绑字段。点击调 onClick
 * 启动 Intent（如 ACTION_OPEN_DOCUMENT_TREE 打开系统文件选择器）。
 */
@Composable
private fun ActionRow(
    label: String,
    hint: String,
    buttonText: String,
    onClick: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (hint.isNotBlank()) {
                    Text(
                        text = hint,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            TextButton(onClick = onClick) {
                Text(buttonText)
            }
        }
    }
}

/**
 * 阶段 9 v0.4.1 启用：把 AppConfig.theme 内部 key 翻译成 UI 显示文字。
 *
 * AppConfig 内部用 `"default_light"` / `"default_dark"` / `"system"`（v0.4.1 引入
 * "system"），UI 用本地化字符串。未知值（v0.1 老配置 / 用户瞎写）回退到
 * "跟随系统"——保守默认值。
 */
@Composable
private fun themeDisplay(key: String): String = when (key) {
    "default_light" -> stringResource(R.string.settings_theme_light)
    "default_dark" -> stringResource(R.string.settings_theme_dark)
    else -> stringResource(R.string.settings_theme_system)
}

/**
 * 阶段 9 v0.4.1 启用：把 AppConfig.duplicatePolicy 内部 key 翻译成 UI 显示文字。
 */
@Composable
private fun duplicateDisplay(key: String): String = when (key) {
    "redownload" -> stringResource(R.string.settings_duplicate_redownload)
    "ask" -> stringResource(R.string.settings_duplicate_ask)
    else -> stringResource(R.string.settings_duplicate_skip)
}
