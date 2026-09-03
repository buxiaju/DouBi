package com.doubi.android.ui.history

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 阶段 6 「历史」tab。1:1 对拍桌面版
 * `src/doubi/ui/pages/history.py:HistoryPage`（LazyColumn + 数据库查询 + 重新下载）。
 *
 * 阶段 3 占位 → 完整 UI：
 * - LazyColumn 渲染每条 MediaItemEntity（按 last_download_time DESC）
 * - 每行：title + author + 下载时间 + 保存目录
 * - 「已删除」标签：fileExists = false 时显示
 * - 行点展开 ActionSheet：打开保存目录 / 重新下载
 * - 空态保留
 */
@Composable
fun HistoryScreen(
    modifier: Modifier = Modifier,
    viewModel: HistoryViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val reenqueuedTemplate = stringResource(R.string.history_reenqueued)
    val redownloadFailedTemplate = stringResource(R.string.history_redownload_failed)

    LaunchedEffect(Unit) {
        viewModel.events.collect { ev ->
            when (ev) {
                is HistoryViewModel.Event.Reenqueued -> {
                    snackbarHostState.showSnackbar(reenqueuedTemplate.format(ev.taskId, ev.title))
                    viewModel.onEventShown()
                }
                is HistoryViewModel.Event.Failure -> {
                    snackbarHostState.showSnackbar(redownloadFailedTemplate.format(ev.error))
                    viewModel.onEventShown()
                }
                is HistoryViewModel.Event.OpenDir -> {
                    // 阶段 6 简化：v0.2.2 阶段 7 加 FileProvider + res/xml/file_paths.xml
                    // 走 Intent.ACTION_VIEW 真正打开系统文件管理器。当前只显示路径。
                    viewModel.onEventShown()
                }
                null -> Unit
            }
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        if (state.items.isEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
            ) {
                Text(
                    text = stringResource(R.string.history_title),
                    style = MaterialTheme.typography.headlineSmall,
                    textAlign = TextAlign.Center,
                )
                Text(
                    text = stringResource(R.string.history_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stringResource(R.string.history_hint_empty),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            Column(modifier = Modifier.fillMaxSize()) {
                Text(
                    text = stringResource(R.string.history_count, state.items.size),
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(items = state.items, key = { "${it.entity.platform}/${it.entity.itemId}" }) { item ->
                        HistoryRow(
                            item = item,
                            onRedownload = { viewModel.onRedownload(item) },
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
private fun HistoryRow(
    item: HistoryViewModel.HistoryItem,
    onRedownload: () -> Unit,
) {
    val entity = item.entity
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (item.fileExists) {
                    Icon(
                        imageVector = Icons.Filled.CheckCircle,
                        contentDescription = stringResource(R.string.history_file_exists),
                        tint = MaterialTheme.colorScheme.tertiary,
                        modifier = Modifier.padding(end = 8.dp),
                    )
                } else {
                    Icon(
                        imageVector = Icons.Filled.Error,
                        contentDescription = stringResource(R.string.history_file_missing),
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(end = 8.dp),
                    )
                }
                Text(
                    text = entity.title ?: entity.itemId,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }
            Row(
                modifier = Modifier.padding(top = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (entity.authorName != null) {
                    Text(
                        text = entity.authorName,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = entity.platform + " · " + formatTime(entity.lastDownloadTime),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (entity.lastSaveDir != null) {
                Text(
                    text = entity.lastSaveDir,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            if (!item.fileExists) {
                Text(
                    text = stringResource(R.string.history_file_missing_label),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
            Row(
                horizontalArrangement = Arrangement.End,
                modifier = Modifier.fillMaxWidth(),
            ) {
                TextButton(onClick = onRedownload) {
                    Text(stringResource(R.string.history_redownload))
                }
            }
        }
    }
}

private fun formatTime(epochSec: Long?): String {
    if (epochSec == null || epochSec <= 0L) return "—"
    val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault())
    return fmt.format(Date(epochSec * 1000L))
}
