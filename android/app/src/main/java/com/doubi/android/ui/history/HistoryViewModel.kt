package com.doubi.android.ui.history

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.doubi.android.data.db.dao.MediaItemDao
import com.doubi.android.data.db.entity.MediaItemEntity
import com.doubi.android.data.repository.DownloadRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File
import javax.inject.Inject

/**
 * 阶段 6 HistoryScreen 的 ViewModel。1:1 对拍桌面版
 * `src/doubi/ui/pages/history.py:HistoryPage`。
 *
 * 数据流：
 * - `MediaItemDao.listRecentFlow()` —— Room 端按 `last_download_time DESC` 查最近 200 条
 * - 文件存在性检查 —— 后台协程查每个 item 的 `lastSaveDir` 目录是否还有文件
 *
 * 重新下载：点行 → `downloadRepo.enqueue(item.sourceUrl, ...)`，从「历史」tab 触发的
 * 二次下载入 WorkManager 队列，跟初次下载同路径，phase 2/3 已落地。
 */
@HiltViewModel
class HistoryViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val mediaItemDao: MediaItemDao,
    private val downloadRepo: DownloadRepository,
) : ViewModel() {

    val state: StateFlow<State> = mediaItemDao.listRecentFlow(limit = 200)
        .map { entities ->
            val fileExistsMap = withContext(Dispatchers.IO) {
                entities.associate { entity ->
                    val key = entity.platform to entity.itemId
                    val exists = checkFileExists(entity)
                    key to exists
                }
            }
            State(
                items = entities.map { entity ->
                    val key = entity.platform to entity.itemId
                    HistoryItem(
                        entity = entity,
                        fileExists = fileExistsMap[key] ?: true,
                    )
                },
            )
        }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000L),
            initialValue = State(),
        )

    private val _events = MutableStateFlow<Event?>(null)
    val events: StateFlow<Event?> = _events

    fun onRedownload(item: HistoryItem) {
        viewModelScope.launch {
            try {
                // sourceUrl 存在 MediaItemEntity.extra（JSON {"source_url": "..."}）——
                // 阶段 6 Worker 落 media_item 时存进去。MediaItemEntity 没 sourceUrl 列
                // （schema 冻结，v0.1 阶段 3 显式 Migration 链已固化），借 extra 字段。
                val sourceUrl = item.entity.extra?.let { extra ->
                    runCatching {
                        org.json.JSONObject(extra).optString("source_url", null)
                    }.getOrNull()
                }?.takeIf { it.isNotBlank() }
                if (sourceUrl == null) {
                    _events.value = Event.Failure("无 sourceUrl（v0.1 阶段 2-3 之前的下载记录未存）")
                    return@launch
                }
                val taskId = downloadRepo.enqueue(
                    sourceUrl = sourceUrl,
                    platform = item.entity.platform,
                    itemId = item.entity.itemId,
                    title = item.entity.title,
                )
                _events.value = Event.Reenqueued(
                    taskId = taskId,
                    title = item.entity.title ?: item.entity.itemId,
                )
            } catch (e: Throwable) {
                Timber.e(e, "redownload failed")
                _events.value = Event.Failure(e.message ?: "redownload failed")
            }
        }
    }

    fun onOpenSaveDir(item: HistoryItem) {
        // 用 Event 把路径回传给 Screen，Screen 用 Intent.ACTION_VIEW + FileProvider
        val dir = item.entity.lastSaveDir ?: return
        _events.value = Event.OpenDir(dir)
    }

    fun onEventShown() {
        _events.value = null
    }

    /**
     * 检查文件是否还存在。简化版：
     * - lastSaveDir 空 → false
     * - lastSaveDir 目录不存在 → false
     * - lastSaveDir 目录里没有任何文件 → false
     * - 否则 true
     *
     * 不反推具体文件名（避免复用 YtDlpEngine.renderTemplate 还要重新构造 DownloadOptions），
     * 用"目录非空"做弱检查。v0.2.2 阶段 7 可补严格检查（用 YtDlpEngine 路径模板）。
     */
    private fun checkFileExists(entity: MediaItemEntity): Boolean {
        val dir = entity.lastSaveDir ?: return false
        val dirFile = File(dir)
        if (!dirFile.exists() || !dirFile.isDirectory) return false
        val children = dirFile.listFiles() ?: return false
        return children.any { it.isFile && it.length() > 0 }
    }

    data class State(
        val items: List<HistoryItem> = emptyList(),
    )

    data class HistoryItem(
        val entity: MediaItemEntity,
        val fileExists: Boolean,
    )

    sealed class Event {
        data class Reenqueued(val taskId: String, val title: String) : Event()
        data class OpenDir(val path: String) : Event()
        data class Failure(val error: String) : Event()
    }
}
