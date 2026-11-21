package com.flacify.android.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        TrackEntity::class,
        PlaylistEntity::class,
        PlaylistTrackEntity::class,
        TrackAliasEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class FlacifyDatabase : RoomDatabase() {
    abstract fun dao(): FlacifyDao

    companion object {
        @Volatile
        private var instance: FlacifyDatabase? = null

        fun getInstance(context: Context): FlacifyDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    FlacifyDatabase::class.java,
                    "flacify_offline.db",
                ).build().also { instance = it }
            }
    }
}
