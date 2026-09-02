package com.doubi.android.ui.parse

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.doubi.android.R
import com.doubi.android.core.model.DownloadOptions
import com.doubi.android.core.model.MediaFormat
import com.doubi.android.core.model.MediaItem
import java.util.Locale

/**
 * 阶段 4：下载前确认弹窗（Compose）。
 *
 * 桌面版对应：`src/doubi/ui/pages/parse.py:PromptOptionsDialog`（PySide6 + qfluentwidgets）。
 * Android 端用 Material 3 [AlertDialog]。
 *
 * **v0.1 范围**（按 PHASES.md L141-156）：
 * - 格式列表（radio，从 `MediaFormat.label` 拿人类可读标签）
 * - 容器（mp4 / mkv，下拉——v0.1 只 mp4 实际生效）
 * - 缩略图 / 字幕 / 断点续传（checkbox）
 * - 标题模板（勾选启用 + 输入框，默认 `{title}`）
 *
 * **v0.1 不做**：写入 metadata.json（桌面版有，Android 端暂不写）、bili23 那种
 * "按行号范围选择"（直链场景下无意义）。
 *
 * `onConfirm(item, format, options)` —— format 为 null 表示 formats 列表为空时
 * 「按 default options 走」分支（直链 / 解析失败兜底）。
 */
@Composable
fun PromptOptionsDialog(
    item: MediaItem,
    formats: List<MediaFormat>,
    seed: DownloadOptions,
    onConfirm: (item: MediaItem, format: MediaFormat?, options: DownloadOptions, titleTemplate: String?) -> Unit,
    onDismiss: () -> Unit,
) {
    var selectedFormatIndex by remember {
        // 默认：第一个非 audio-only（v0.1 倾向视频优先）；全 audio-only 就拿第一个
        mutableStateOf(
            formats.indexOfFirst { !it.isAudioOnly }.coerceAtLeast(0)
                .let { if (it >= formats.size) 0 else it }
        )
    }
    var container by remember { mutableStateOf(seed.container) }
    var writeThumbnail by remember { mutableStateOf(seed.writeThumbnail) }
    var writeSubtitles by remember { mutableStateOf(seed.writeSubtitles) }
    var resume by remember { mutableStateOf(seed.resume) }
    var enableTitleTemplate by remember { mutableStateOf(false) }
    var titleTemplate by remember { mutableStateOf("{title}") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.prompt_title)) },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    text = item.title.ifBlank { item.sourceUrl },
                    style = MaterialTheme.typography.titleSmall,
                )
                item.author?.name?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(8.dp))
                Divider()
                Spacer(Modifier.height(8.dp))

                // ---- formats 列表（v0.1：单选 radio） ----
                if (formats.isNotEmpty()) {
                    Text(
                        text = stringResource(R.string.prompt_section_format),
                        style = MaterialTheme.typography.labelLarge,
                    )
                    Spacer(Modifier.height(4.dp))
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 240.dp),
                    ) {
                        LazyColumn {
                            items(formats.size) { idx ->
                                val f = formats[idx]
                                FormatRow(
                                    label = f.label,
                                    selected = idx == selectedFormatIndex,
                                    onSelect = { selectedFormatIndex = idx },
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Divider()
                    Spacer(Modifier.height(8.dp))
                }

                // ---- 容器 / 缩略图 / 字幕 / 续传 ----
                Text(
                    text = stringResource(R.string.prompt_section_options),
                    style = MaterialTheme.typography.labelLarge,
                )
                Spacer(Modifier.height(4.dp))
                ContainerDropdown(
                    value = container,
                    onChange = { container = it },
                )
                Spacer(Modifier.height(4.dp))
                CheckboxRow(
                    label = stringResource(R.string.prompt_write_thumbnail),
                    checked = writeThumbnail,
                    onChange = { writeThumbnail = it },
                )
                CheckboxRow(
                    label = stringResource(R.string.prompt_write_subtitles),
                    checked = writeSubtitles,
                    onChange = { writeSubtitles = it },
                )
                CheckboxRow(
                    label = stringResource(R.string.prompt_resume),
                    checked = resume,
                    onChange = { resume = it },
                )

                Spacer(Modifier.height(8.dp))
                Divider()
                Spacer(Modifier.height(8.dp))

                // ---- 标题模板（v0.1 范围，但先用简化版） ----
                CheckboxRow(
                    label = stringResource(R.string.prompt_modify_title),
                    checked = enableTitleTemplate,
                    onChange = { enableTitleTemplate = it },
                )
                if (enableTitleTemplate) {
                    Spacer(Modifier.height(4.dp))
                    OutlinedTextField(
                        value = titleTemplate,
                        onValueChange = { titleTemplate = it },
                        label = { Text(stringResource(R.string.prompt_title_template)) },
                        placeholder = { Text("{title}") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val selectedFormat = formats.getOrNull(selectedFormatIndex)
                val newOptions = DownloadOptions(
                    maxQuality = selectedFormat?.formatId ?: seed.maxQuality,
                    container = container,
                    writeThumbnail = writeThumbnail,
                    writeSubtitles = writeSubtitles,
                    resume = resume,
                    filenameTemplate = seed.filenameTemplate,
                    rateLimit = seed.rateLimit,
                    proxy = seed.proxy,
                    outputRoot = seed.outputRoot,
                    outputDirTemplate = seed.outputDirTemplate,
                )
                onConfirm(
                    item,
                    selectedFormat,
                    newOptions,
                    titleTemplate.takeIf { enableTitleTemplate && it.isNotBlank() },
                )
            }) {
                Text(stringResource(R.string.prompt_action_download))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.prompt_action_cancel))
            }
        },
    )
}

@Composable
private fun FormatRow(label: String, selected: Boolean, onSelect: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .selectable(
                selected = selected,
                onClick = onSelect,
                role = Role.RadioButton,
            )
            .padding(vertical = 4.dp, horizontal = 4.dp),
    ) {
        RadioButton(selected = selected, onClick = null)
        Spacer(Modifier.width(8.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun ContainerDropdown(
    value: String,
    onChange: (String) -> Unit,
) {
    val options = listOf("mp4", "mkv")
    // v0.1 简化：用 ExposedDropdownMenu 改用 Row + Box + clickable 切选项
    // 因为不想拉 ExposedDropdownMenuBox 进 build 依赖。
    Column {
        Text(
            text = stringResource(R.string.prompt_container),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            options.forEach { opt ->
                Box(
                    modifier = Modifier
                        .background(
                            if (opt == value) MaterialTheme.colorScheme.primaryContainer
                            else MaterialTheme.colorScheme.surfaceVariant,
                            shape = MaterialTheme.shapes.small,
                        )
                        .clickable { onChange(opt) }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                ) {
                    Text(
                        text = opt.uppercase(Locale.US),
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        }
    }
}

@Composable
private fun CheckboxRow(
    label: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onChange(!checked) }
            .padding(vertical = 2.dp),
    ) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(text = label, style = MaterialTheme.typography.bodyMedium)
    }
}
