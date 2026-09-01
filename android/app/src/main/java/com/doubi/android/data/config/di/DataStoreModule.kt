package com.doubi.android.data.config.di

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStoreFile
import com.doubi.android.data.config.AppConfigDataStore
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import javax.inject.Singleton

/**
 * DataStore + Hilt 装配。
 *
 * 桌面版对照：`src/doubi/ui/app.py:create_app()` 里的 `AppConfig` 装配。
 *
 * 路径：`Context.dataStore` 推荐的 `preferencesDataStoreFile("doubi_config")`
 * 会解析到 `/data/data/com.doubi.android/files/datastore/doubi_config.preferences_pb`，
 * 跟随 app 卸载一起清掉。**不复刻桌面版 `database_path` 相对路径的卸载残留坑**。
 */
@Module
@InstallIn(SingletonComponent::class)
object DataStoreModule {

    private const val DATASTORE_NAME = "doubi_config"

    @Provides
    @Singleton
    fun providePreferencesDataStore(
        @ApplicationContext context: Context,
    ): DataStore<Preferences> = PreferenceDataStoreFactory.create(
        scope = CoroutineScope(Dispatchers.IO + SupervisorJob()),
        produceFile = { context.preferencesDataStoreFile(DATASTORE_NAME) },
    )

    @Provides
    @Singleton
    fun provideAppConfigDataStore(
        dataStore: DataStore<Preferences>,
    ): AppConfigDataStore = AppConfigDataStore(dataStore)
}
