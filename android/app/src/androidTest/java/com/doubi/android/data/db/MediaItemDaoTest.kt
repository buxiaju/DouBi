package com.doubi.android.data.db

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.doubi.android.data.db.entity.MediaItemEntity
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * MediaItemDao 仪器测试（跑在真机 / 模拟器上）。
 *
 * 桌面版对照：`tests/test_storage.py` 里 `TestDatabase` / `TestRecordDownload` /
 * `TestListByAuthor` / `TestListRecent` 几个用例。
 *
 * 关键断言（与桌面版一对一）：
 * - 插入后 `is_downloaded` 返回 true
 * - 同 (platform, item_id) 二次插入走 REPLACE 策略
 * - `list_recent` 按 `last_download_time` 倒序
 * - `delete` 移除后 `is_downloaded` 变 false
 * - 索引建好后 query plan 用上索引（这一条 Room 不暴露 EXPLAIN，暂跳过）
 */
@RunWith(AndroidJUnit4::class)
class MediaItemDaoTest {
    private lateinit var db: DouBiDatabase
    private lateinit var dao: com.doubi.android.data.db.dao.MediaItemDao

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        // in-memory 数据库，测试结束自动释放
        db = Room.inMemoryDatabaseBuilder(context, DouBiDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        dao = db.mediaItemDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun upsertAndIsDownloaded() = runTest {
        val item = sampleItem(platform = "youtube", itemId = "dQw4w9WgXcQ", downloadTime = 1_000L)
        dao.upsert(item)
        assertThat(dao.isDownloaded("youtube", "dQw4w9WgXcQ")).isTrue()
        // 平台不同不算同一条
        assertThat(dao.isDownloaded("bilibili", "dQw4w9WgXcQ")).isFalse()
    }

    @Test
    fun upsertReplacesOnConflict() = runTest {
        val original = sampleItem(platform = "youtube", itemId = "abc", title = "old", downloadTime = 1L)
        val updated = original.copy(title = "new", lastDownloadTime = 2L)
        dao.upsert(original)
        dao.upsert(updated)
        val got = dao.getItem("youtube", "abc")
        assertThat(got?.title).isEqualTo("new")
        assertThat(got?.lastDownloadTime).isEqualTo(2L)
        // 仍然只有一条
        assertThat(dao.count()).isEqualTo(1)
    }

    @Test
    fun listRecent_ordersByDownloadTimeDesc() = runTest {
        dao.upsert(sampleItem("youtube", "a", downloadTime = 100L))
        dao.upsert(sampleItem("youtube", "b", downloadTime = 300L))
        dao.upsert(sampleItem("youtube", "c", downloadTime = 200L))
        val list = dao.listRecent()
        assertThat(list.map { it.itemId }).containsExactly("b", "c", "a").inOrder()
    }

    @Test
    fun listByAuthor_filtersAndOrders() = runTest {
        dao.upsert(sampleItem("youtube", "v1", authorId = "u1", downloadTime = 100L))
        dao.upsert(sampleItem("youtube", "v2", authorId = "u1", downloadTime = 200L))
        dao.upsert(sampleItem("youtube", "v3", authorId = "u2", downloadTime = 300L))
        val list = dao.listByAuthor("youtube", "u1")
        assertThat(list.map { it.itemId }).containsExactly("v2", "v1").inOrder()
    }

    @Test
    fun deleteRemovesRow() = runTest {
        dao.upsert(sampleItem("youtube", "x"))
        assertThat(dao.delete("youtube", "x")).isEqualTo(1)
        assertThat(dao.isDownloaded("youtube", "x")).isFalse()
        // 删不存在的返回 0
        assertThat(dao.delete("youtube", "x")).isEqualTo(0)
    }

    @Test
    fun isDownloadedFlow_emitsUpdates() = runTest {
        dao.upsert(sampleItem("youtube", "live"))
        val flow = dao.isDownloadedFlow("youtube", "live")
        assertThat(flow.first()).isTrue()
        dao.delete("youtube", "live")
        assertThat(flow.first()).isFalse()
    }

    private fun sampleItem(
        platform: String,
        itemId: String,
        authorId: String? = null,
        title: String? = "test title",
        downloadTime: Long? = null,
    ) = MediaItemEntity(
        platform = platform,
        itemId = itemId,
        title = title,
        authorId = authorId,
        authorName = authorId?.let { "Author $it" },
        coverUrl = null,
        duration = 60.0,
        publishTime = 0L,
        mediaType = "video",
        payload = """{"id":"$itemId"}""",
        lastDownloadTime = downloadTime,
        lastSaveDir = "/storage/emulated/0/Download/$platform/$itemId.mp4",
        extra = null,
    )
}
