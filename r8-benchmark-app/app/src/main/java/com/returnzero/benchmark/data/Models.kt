package com.returnzero.benchmark.data

import kotlinx.serialization.Serializable

@Serializable
data class Article(
    val id: Int,
    val title: String,
    val body: String,
    val authorId: Int,
    val imageUrl: String
)

@Serializable
data class Author(
    val id: Int,
    val name: String,
    val avatarUrl: String
)

@Serializable
data class FeedResponse(
    val articles: List<Article>,
    val authors: List<Author>
)