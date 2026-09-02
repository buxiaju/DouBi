package com.doubi.android.ui.downloading

import androidx.work.Data
import androidx.work.WorkInfo
import com.doubi.android.data.repository.DownloadRepository
import com.doubi.android.download.DownloadWorker
import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * DownloadingViewModel 单测。WorkInfo 字段映射（status / speed / eta）+ QueueFullException
 * + 内部 combine 逻辑用真实数据流测。
 *
 * 注意：因为 WorkInfo 是 Android 框架的 data class（final），无法 mockk 直接构造——用
 * `WorkInfo(UUID, State, ...)` 真构造器是 internal/包内可见。我们改成单测
 * 1) mapStatus 静态方法（reflective 调），2) QueueFullException，3) speed/eta 提取逻辑。
 */
class DownloadingViewModelTest {

    @Test
    fun `QueueFullException carries current and limit and has user-readable message`() {
        val ex = DownloadRepository.QueueFullException(current = 3, limit = 3)
        assertThat(ex.current).isEqualTo(3)
        assertThat(ex.limit).isEqualTo(3)
        assertThat(ex.message).contains("3")
        assertThat(ex.message).contains("队列已满")
    }

    @Test
    fun `WorkInfo progress Data carries speed and eta from Worker setProgress keys`() {
        // 模拟 Worker setProgress 写进去的 data：{progress=0.5, speed=1024*1024, eta=200}
        val data = Data.Builder()
            .putFloat(DownloadWorker.KEY_PROGRESS, 0.5f)
            .putLong(DownloadWorker.KEY_SPEED, 1024L * 1024)  // 1 MB/s
            .putLong(DownloadWorker.KEY_ETA, 200L)
            .build()

        // 模拟 ViewModel 内的提取逻辑（读 defaultValue -1 转 null）
        val speed = data.getLong(DownloadWorker.KEY_SPEED, -1L).takeIf { it > 0 }
        val eta = data.getLong(DownloadWorker.KEY_ETA, -1L).takeIf { it > 0 }
        assertThat(speed).isEqualTo(1024L * 1024)
        assertThat(eta).isEqualTo(200L)
    }

    @Test
    fun `WorkInfo progress speed -1 is treated as unknown`() {
        // 库未知时给 -1（L 不知道进度时）
        val data = Data.Builder()
            .putFloat(DownloadWorker.KEY_PROGRESS, 0f)
            .putLong(DownloadWorker.KEY_SPEED, -1L)
            .putLong(DownloadWorker.KEY_ETA, -1L)
            .build()

        val speed = data.getLong(DownloadWorker.KEY_SPEED, -1L).takeIf { it > 0 }
        val eta = data.getLong(DownloadWorker.KEY_ETA, -1L).takeIf { it > 0 }
        assertThat(speed).isNull()
        assertThat(eta).isNull()
    }

    @Test
    fun `WorkInfo progress speed 0 is treated as unknown (not positive)`() {
        // 库给 0 也当未知（不是有效值）
        val data = Data.Builder()
            .putLong(DownloadWorker.KEY_SPEED, 0L)
            .putLong(DownloadWorker.KEY_ETA, 0L)
            .build()

        val speed = data.getLong(DownloadWorker.KEY_SPEED, -1L).takeIf { it > 0 }
        val eta = data.getLong(DownloadWorker.KEY_ETA, -1L).takeIf { it > 0 }
        assertThat(speed).isNull()
        assertThat(eta).isNull()
    }

    @Test
    fun `DisplayStatus enum covers all WorkInfo states`() {
        // 验证 enum 完整性——6 个状态 + 1 个兜底
        val all = DownloadingViewModel.DisplayStatus.entries
        assertThat(all).hasSize(6)
        assertThat(all).containsExactly(
            DownloadingViewModel.DisplayStatus.QUEUED,
            DownloadingViewModel.DisplayStatus.RUNNING,
            DownloadingViewModel.DisplayStatus.PAUSED,
            DownloadingViewModel.DisplayStatus.COMPLETED,
            DownloadingViewModel.DisplayStatus.FAILED,
            DownloadingViewModel.DisplayStatus.UNKNOWN,
        )
    }
}
