package com.returnzero.benchmark.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.returnzero.benchmark.data.Article
import com.returnzero.benchmark.data.Author
import com.returnzero.benchmark.data.FeedResponse
import com.returnzero.benchmark.db.AppDatabase
import com.returnzero.benchmark.db.ArticleEntity
import com.returnzero.benchmark.network.Network
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json

class FeedViewModel(app: Application) : AndroidViewModel(app) {
    private val db = AppDatabase.get(app)

    private val _feed = MutableStateFlow(SyntheticFeed)
    val feed: StateFlow<List<Article>> = _feed

    private val _authors = MutableStateFlow(SyntheticAuthors)
    val authors: StateFlow<List<Author>> = _authors

    private val _status = MutableStateFlow("idle")
    val status: StateFlow<String> = _status

    init {
        loadFromDb()
        fetchFromNetwork()
    }

    private fun loadFromDb() {
        viewModelScope.launch(Dispatchers.IO) {
            val rows = db.articleDao().getAll()
            if (rows.isNotEmpty()) {
                _feed.value = rows.map { Article(it.id, it.title, it.body, it.authorId, it.imageUrl) }
                _status.value = "loaded ${rows.size} from db"
            }
        }
    }

    private fun fetchFromNetwork() {
        viewModelScope.launch(Dispatchers.IO) {
            _status.value = "fetching"
            try {
                val resp = Network.service.getFeed()
                _feed.value = resp.articles
                _authors.value = resp.authors
                db.articleDao().clear()
                db.articleDao().insertAll(resp.articles.map {
                    ArticleEntity(it.id, it.title, it.body, it.authorId, it.imageUrl)
                })
                _status.value = "fetched ${resp.articles.size}"
            } catch (e: Exception) {
                _status.value = "net failed, using synthetic: ${e.message}"
            }
        }
    }
}

// Synthetic data so the app renders content even without network. This also
// guarantees kotlinx.serialization is exercised: the JSON is parsed at startup.
private val SyntheticJson = """
{"articles":[{"id":1,"title":"R8 shrinking in practice","body":"Real numbers from a real app.","authorId":1,"imageUrl":"https://returnzero.dev/images/a1.png"},{"id":2,"title":"Memory limiter per-process","body":"Each process gets its own cgroup.","authorId":2,"imageUrl":"https://returnzero.dev/images/a2.png"},{"id":3,"title":"Cold start optimization","body":"Baseline profiles and lazy init.","authorId":1,"imageUrl":"https://returnzero.dev/images/a3.png"}],"authors":[{"id":1,"name":"Rotem","avatarUrl":"https://returnzero.dev/images/rotem.png"},{"id":2,"name":"Miri","avatarUrl":"https://returnzero.dev/images/miri.png"}]}
""".trim()

private val Json = Json { ignoreUnknownKeys = true }
private val SyntheticFeed: List<Article> = Json.decodeFromString<FeedResponse>(SyntheticJson).articles
private val SyntheticAuthors: List<Author> = Json.decodeFromString<FeedResponse>(SyntheticJson).authors