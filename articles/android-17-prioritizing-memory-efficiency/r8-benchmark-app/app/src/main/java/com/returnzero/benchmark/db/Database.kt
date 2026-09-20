package com.returnzero.benchmark.db

import androidx.room.Entity
import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import android.content.Context

@Entity(tableName = "articles")
data class ArticleEntity(
    @androidx.room.PrimaryKey val id: Int,
    val title: String,
    val body: String,
    val authorId: Int,
    val imageUrl: String
)

@Dao
interface ArticleDao {
    @Insert
    suspend fun insertAll(articles: List<ArticleEntity>)

    @Query("SELECT * FROM articles ORDER BY id LIMIT 50")
    suspend fun getAll(): List<ArticleEntity>

    @Query("DELETE FROM articles")
    suspend fun clear()
}

@Database(entities = [ArticleEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun articleDao(): ArticleDao

    companion object {
        @Volatile private var INSTANCE: AppDatabase? = null
        fun get(context: Context): AppDatabase =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "benchmark.db"
                ).build().also { INSTANCE = it }
            }
    }
}