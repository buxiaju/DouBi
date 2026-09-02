package com.doubi.android.ui.downloading

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.doubi.android.R
import com.doubi.android.core.model.Progress

/**
 * 阶段 5 「下载中」tab。
 *
 * 阶段 3 占位 → 完整 UI：
 * - LazyColumn 渲染每个 active 任务
 * - 每行：title + 进度条 + `Progress.statusLine()` 一行式状态 + 取消按钮
 * - 空态保留
 * - 速度 / ETA 走 `Progress.formatSpeed` / `Progress.formatEta` 复用阶段 4 的格式化
 */
@Composable
fun DownloadingScreen(
    modifier: Modifier = Modifier,
    viewModel: DownloadingViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val cancelMsg = stringResource(R.string.downloading_cancelled)

    LaunchedEffect(Unit) {
        viewModel.events.collect { ev ->
            when (ev) {
                is DownloadingViewModel.Event.Cancelled -> {
                    snackbarHostState.showSnackbar(cancelMsg.format(ev.taskId))
                    viewModel.onEventShown()
                }
                null -> Unit
            }
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        if (state.tasks.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
            ) {
                Text(
                    text = stringResource(R.string.downloading_title),
                    style = MaterialTheme.typography.headlineSmall,
                    textAlign = TextAlign.Center,
                )
                Text(
                    text = stringResource(R.string.downloading_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            Column(modifier = Modifier.fillMaxSize()) {
                Text(
                    text = stringResource(R.string.downloading_count, state.tasks.size),
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(items = state.tasks, key = { it.taskId }) { task ->
                        TaskRow(
                            task = task,
                            onCancel = { viewModel.onCancelClicked(task.taskId) },
                        )
                    }
                }
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
private fun TaskRow(
    task: DownloadingViewModel.TaskUiState,
    onCancel: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = task.title,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer8()
                if (task.status == DownloadingViewModel.DisplayStatus.RUNNING) {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .padding(end = 4.dp)
                            .padding(2.dp),
                        strokeWidth = 2.dp,
                    )
                }
                Text(
                    text = statusLabel(task.status),
                    style = MaterialTheme.typography.labelSmall,
                    color = statusColor(task.status),
                )
            }
            Spacer8()
            val p = Progress(
                fraction = task.fraction,
                speedBytesPerSec = task.speedBytesPerSec,
                etaSeconds = task.etaSeconds,
            )
            Text(
                text = p.statusLine(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer8()
            LinearProgressIndicator(
                progress = { task.fraction.coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth(),
            )
            if (task.message != null && task.message.isNotBlank() && task.status == DownloadingViewModel.DisplayStatus.FAILED) {
                Spacer8()
                Text(
                    text = task.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (task.isCancellable) {
                Spacer8()
                HorizontalDivider()
                Row(
                    horizontalArrangement = Arrangement.End,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    TextButton(onClick = onCancel) {
                        Text(stringResource(R.string.downloading_cancel))
                    }
                }
            }
        }
    }
}

@Composable
private fun Spacer8() {
    Box(modifier = Modifier.padding(top = 4.dp))
}

@Composable
private fun statusLabel(status: DownloadingViewModel.DisplayStatus): String = when (status) {
    DownloadingViewModel.DisplayStatus.QUEUED -> stringResource(R.string.downloading_status_queued)
    DownloadingViewModel.DisplayStatus.RUNNING -> stringResource(R.string.downloading_status_running)
    DownloadingViewModel.DisplayStatus.PAUSED -> stringResource(R.string.downloading_status_paused)
    DownloadingViewModel.DisplayStatus.COMPLETED -> stringResource(R.string.downloading_status_completed)
    DownloadingViewModel.DisplayStatus.FAILED -> stringResource(R.string.downloading_status_failed)
    DownloadingViewModel.DisplayStatus.UNKNOWN -> stringResource(R.string.downloading_status_unknown)
}

@Composable
private fun statusColor(status: DownloadingViewModel.DisplayStatus) = when (status) {
    DownloadingViewModel.DisplayStatus.RUNNING -> MaterialTheme.colorScheme.primary
    DownloadingViewModel.DisplayStatus.COMPLETED -> MaterialTheme.colorScheme.tertiary
    DownloadingViewModel.DisplayStatus.FAILED -> MaterialTheme.colorScheme.error
    DownloadingViewModel.DisplayStatus.PAUSED -> MaterialTheme.colorScheme.secondary
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}
