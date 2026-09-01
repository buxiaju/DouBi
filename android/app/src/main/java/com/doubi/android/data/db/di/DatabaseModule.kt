package com.doubi.android.data.db.di

import android.content.Context
import androidx.room.Room
import androidx.room.RoomDatabase
import com.doubi.android.data.db.DouBiDatabase
import com.doubi.android.data.db.dao.IncrementCheckpointDao
import com.doubi.android.data.db.dao.MediaItemDao
import com.doubi.android.data.db.dao.PendingTaskDao
import com.doubi.android.data.db.dao.TaskDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Room + Hilt 装配。
 *
 * 桌面版对照：`src/doubi/ui/app.py:create_app()` 里的 `Database` 装配。
 *
 * 设计决定：
 * - **绝对路径**：用 `Context.getDatabasePath()`，不复刻桌面版 `database_path`
 *   相对路径导致的卸载残留坑（详见桌面版 BUILD §6.5）
 * - **WAL**：Room 默认启用
 * - **Destructive migration**：v0.1 没有历史 schema 负担，从 v2 起用
 *   `fallbackToDestructiveMigration()` 仅在 dev 阶段可用，release 必须写 Migration
 */
@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): DouBiDatabase {
        return Room.databaseBuilder(
            context,
            DouBiDatabase::class.java,
            DouBiDatabase.DATABASE_NAME,
        )
            // v0.1：仅有 schema v1，升级时直接重建（dev only）
            // Room 2.7+ 可加 `dropAllTables = true` 显式清空所有表；2.6 默认就是删全部
            .fallbackToDestructiveMigration()
            .build()
    }

    @Provides
    fun provideMediaItemDao(db: DouBiDatabase): MediaItemDao = db.mediaItemDao()

    @Provides
    fun provideTaskDao(db: DouBiDatabase): TaskDao = db.taskDao()

    @Provides
    fun providePendingTaskDao(db: DouBiDatabase): PendingTaskDao = db.pendingTaskDao()

    @Provides
    fun provideIncrementCheckpointDao(db: DouBiDatabase): IncrementCheckpointDao = db.incrementCheckpointDao()
}
