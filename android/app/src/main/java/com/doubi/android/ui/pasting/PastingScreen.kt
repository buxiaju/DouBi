package com.doubi.android.ui.pasting

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.doubi.android.R

/**
 * 阶段 3 「粘贴」tab。
 *
 * 桌面版对照：`ui/main_window.py:MainWindow` 的「下载」page（含 URL 输入框 + 解析按钮）。
 * 阶段 3 只做 UI 框架：输入框 + 解析按钮可点击，但**不真的入队**。
 * 阶段 4 接嗅探（Engine.probe），阶段 5 接 DownloadRepository.enqueue。
 *
 * 校验：点完解析按钮 → 跳到 NavRoutes.PARSING（阶段 4 用 URL 参数；阶段 3 不带）。
 */
@Composable
fun PastingScreen(
    modifier: Modifier = Modifier,
    viewModel: PastingViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Column(
        modifier = modifier
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
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { viewModel.onParseClicked() },
            enabled = state.url.isNotBlank(),
        ) {
            Text(stringResource(R.string.pasting_action))
        }
        Text(
            text = stringResource(R.string.pasting_disabled),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}
