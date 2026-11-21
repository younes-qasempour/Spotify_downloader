package com.flacify.android.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        TrackEntity::class,
        PlaylistEntity::class,
        PlaylistTrackEntity::class,
        TrackAliasEntity::class,
        PendingShareEntity::class,
    ],
    version = 2,
    exportSchema = false,
)
abstract class FlacifyDatabase : RoomDatabase() {
    abstract fun dao(): FlacifyDao

    companion object {
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS `pending_shares` (
                        `id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                        `rawUrl` TEXT NOT NULL,
                        `displayKind` TEXT NOT NULL,
                        `autoDownload` INTEGER NOT NULL,
                        `status` TEXT NOT NULL,
                        `queuedCount` INTEGER NOT NULL,
                        `lastError` TEXT,
                        `createdAt` INTEGER NOT NULL,
                        `updatedAt` INTEGER NOT NULL
                    )
                    """.trimIndent()
                )
            }
        }

        @Volatile
        private var instance: FlacifyDatabase? = null

        fun getInstance(context: Context): FlacifyDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    FlacifyDatabase::class.java,
                    "flacify_offline.db",
                )
                    .addMigrations(MIGRATION_1_2)
                    .build()
                    .also { instance = it }
            }
    }
}
