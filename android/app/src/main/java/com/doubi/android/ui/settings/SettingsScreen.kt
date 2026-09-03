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
    Box(modifier = modifier.fillMaxSize()) {
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
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
