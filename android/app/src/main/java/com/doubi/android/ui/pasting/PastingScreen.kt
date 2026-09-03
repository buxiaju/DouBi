package com.doubi.android.ui.pasting

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.doubi.android.R
import com.doubi.android.ui.parse.PromptOptionsDialog

/**
 * 阶段 4 「粘贴」tab。
 *
 * 桌面版对照：`ui/main_window.py:MainWindow` 的「下载」page。桌面版 UI 复杂
 * （多 URL / 搜索 / 全选 / 表格），v0.1 Android 端只做单 URL 流程——
 * 多 URL 解析 + 容器展开留 v0.2+ 阶段 5/6。
 *
 * 流程：
 * 1. 用户粘 URL
 * 2. 点「解析」→ onParseClicked → ParseAndExpandUseCase
 * 3. 解析成功 → 弹 PromptOptionsDialog 选 format + 附加选项
 * 4. Dialog 确认 → onDialogConfirm → DownloadRepository.enqueue
 * 5. 解析失败 / Unsupported / Enqueued → snackbar 一次性反馈
 */
@Composable
fun PastingScreen(
    modifier: Modifier = Modifier,
    viewModel: PastingViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    // 一次性消息（Unsupported / Enqueued / Failure / QueueFull）→ snackbar 显示后回 Idle
    val unsupportedMsg = stringResource(R.string.pasting_unsupported, "%s")
    val enqueuedMsg = stringResource(R.string.pasting_enqueued, "%s")
    val parseFailedMsg = stringResource(R.string.pasting_parse_failed, "%s")
    val urlEmptyMsg = stringResource(R.string.pasting_url_empty)
    val parsingMsg = stringResource(R.string.pasting_parsing)
    // 阶段 8 v0.4.0：Sniffing 状态提示。Sniffer 在嗅探非 YouTube URL（HEAD 10s 上限），
    // 跟 Parsing 区别开让用户知道"为啥这条 URL 卡了一会"。
    val sniffingMsg = stringResource(R.string.pasting_sniffing)
    // 注意：不能直接 stringResource(R.string.pasting_queue_full, "%1$d", "%2$d")，
    // 因为 Kotlin String literal 会把 "$d" 解析成变量引用。改成读模板 + String.format。
    val queueFullTemplate = stringResource(R.string.pasting_queue_full)

    // 阶段 8 v0.4.0：Loading 状态合集。Parsing（YouTube） + Sniffing（其他 URL）都是
    // "等 use case 返回"中——共享一个 CircularProgressIndicator，仅文案不同。
    val isLoading = state.parseStatus is PastingViewModel.ParseStatus.Parsing ||
        state.parseStatus is PastingViewModel.ParseStatus.Sniffing
    val loadingText = if (state.parseStatus is PastingViewModel.ParseStatus.Sniffing) {
        sniffingMsg
    } else {
        parsingMsg
    }

    LaunchedEffect(state.parseStatus) {
        when (val s = state.parseStatus) {
            is PastingViewModel.ParseStatus.Unsupported -> {
                if (s.reason == "URL 为空") {
                    snackbarHostState.showSnackbar(urlEmptyMsg)
                } else {
                    snackbarHostState.showSnackbar(unsupportedMsg.format(s.reason))
                }
                viewModel.onMessageShown()
            }
            is PastingViewModel.ParseStatus.Enqueued -> {
                snackbarHostState.showSnackbar(enqueuedMsg.format(s.title.ifBlank { s.taskId }))
                viewModel.onMessageShown()
            }
            is PastingViewModel.ParseStatus.QueueFull -> {
                snackbarHostState.showSnackbar(queueFullTemplate.format(s.current, s.limit))
                viewModel.onMessageShown()
            }
            is PastingViewModel.ParseStatus.Failure -> {
                snackbarHostState.showSnackbar(parseFailedMsg.format(s.error))
                viewModel.onMessageShown()
            }
            else -> Unit
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        ) {
            Text(
                text = stringResource(R.string.pasting_title),
                style = MaterialTheme.typography.headlineSmall,
                textAlign = TextAlign.Center,
            )
            OutlinedTextField(
                value = state.url,
                onValueChange = viewModel::onUrlChanged,
                label = { Text(stringResource(R.string.pasting_hint)) },
                singleLine = true,
                enabled = !isLoading,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { viewModel.onParseClicked() },
                enabled = state.url.isNotBlank() && !isLoading,
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .padding(end = 8.dp)
                            .fillMaxWidth(0.1f),
                        strokeWidth = 2.dp,
                    )
                    Text(loadingText)
                } else {
                    Text(stringResource(R.string.pasting_action))
                }
            }
            Text(
                text = "解析成功后弹「下载选项」选清晰度，确认后入队。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }

        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(16.dp),
        )

        // 解析成功后弹 Dialog
        (state.parseStatus as? PastingViewModel.ParseStatus.AwaitingConfirm)?.let { awaiting ->
            PromptOptionsDialog(
                item = awaiting.item,
                formats = awaiting.formats,
                seed = awaiting.seedOptions,
                onConfirm = { item, format, options, titleTemplate ->
                    viewModel.onDialogConfirm(item, format, options, titleTemplate)
                },
                onDismiss = { viewModel.onDialogDismiss() },
            )
        }
    }
}
