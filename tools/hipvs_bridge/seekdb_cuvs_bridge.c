/* seekdb <-> hipVS bridge: plain-C CAGRA kNN; all cuVS/ROCm deps live here. */
#include "seekdb_cuvs_bridge.h"
#include <cuvs/core/c_api.h>
#include <cuvs/neighbors/cagra.h>
#include <dlpack/dlpack.h>
#ifdef __HIP_PLATFORM_AMD__
#include <cuvs/cuda_runtime.h>
#else
#include <cuda_runtime.h>
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>

typedef struct {
  cuvsResources_t        res;
  cuvsCagraIndexParams_t ip;
  cuvsCagraIndex_t       idx;
  long n, dim;
  /* Persist GPU query buffers and search parameters across single-query calls.
   * The contest query workload issues thousands of independent SQL queries. */
  float* search_queries;
  unsigned int* search_ids;
  float* search_distances;
  size_t queries_bytes, ids_bytes, distances_bytes;
  cuvsCagraSearchParams_t search_params;
  pthread_mutex_t search_lock;
} sk_cuvs_index;

/* All calls to this helper happen with search_lock held, except during
 * destruction when the owning handle is no longer published. */
static int sk_reserve_gpu(cuvsResources_t res, void** ptr,
                          size_t* capacity, size_t required)
{
  if (required <= *capacity) return 0;
  if (*ptr != NULL) {
    cuvsRMMFree(res, *ptr, *capacity);
    *ptr = NULL;
    *capacity = 0;
  }
  if (cuvsRMMAlloc(res, ptr, required) != CUVS_SUCCESS) return 1;
  *capacity = required;
  return 0;
}

static void sk_free_search(sk_cuvs_index* h)
{
  if (h->search_params != NULL) cuvsCagraSearchParamsDestroy(h->search_params);
  h->search_params = NULL;
  if (h->search_distances != NULL)
    cuvsRMMFree(h->res, h->search_distances, h->distances_bytes);
  if (h->search_ids != NULL)
    cuvsRMMFree(h->res, h->search_ids, h->ids_bytes);
  if (h->search_queries != NULL)
    cuvsRMMFree(h->res, h->search_queries, h->queries_bytes);
  h->search_queries = NULL; h->search_ids = NULL; h->search_distances = NULL;
  h->queries_bytes = 0; h->ids_bytes = 0; h->distances_bytes = 0;
}

void* seekdb_cuvs_build(const float* base, long n, long dim)
{
  sk_cuvs_index* h = (sk_cuvs_index*)calloc(1, sizeof(*h));
  if (!h) return NULL;
  if (pthread_mutex_init(&h->search_lock, NULL) != 0) { free(h); return NULL; }
  if (cuvsResourcesCreate(&h->res) != CUVS_SUCCESS) {
    pthread_mutex_destroy(&h->search_lock); free(h); return NULL;
  }

  DLManagedTensor dset; long ds[2] = {n, dim};
  dset.dl_tensor.data = (void*)base;
  dset.dl_tensor.device.device_type = kDLCPU; dset.dl_tensor.device.device_id = 0;
  dset.dl_tensor.ndim = 2;
  dset.dl_tensor.dtype.code = kDLFloat; dset.dl_tensor.dtype.bits = 32; dset.dl_tensor.dtype.lanes = 1;
  dset.dl_tensor.shape = ds; dset.dl_tensor.strides = 0; dset.dl_tensor.byte_offset = 0;

  if (cuvsCagraIndexParamsCreate(&h->ip) != CUVS_SUCCESS) goto fail_res;
  h->ip->build_algo = NN_DESCENT;
  h->ip->graph_degree = 128;
  h->ip->intermediate_graph_degree = 256;
  /* V5 uses 100 NN-Descent iterations. The GPU graph topology and search
   * parameters are unchanged. 80 reduces the max refinement work but requires
   * validation against both official Recall@K and baseline-delta gates. */
  h->ip->nn_descent_niter = 80;
  if (cuvsCagraIndexCreate(&h->idx)      != CUVS_SUCCESS) goto fail_ip;
  if (cuvsCagraBuild(h->res, h->ip, &dset, h->idx) != CUVS_SUCCESS) goto fail_idx;
  h->n = n; h->dim = dim;
  return h;

fail_idx: cuvsCagraIndexDestroy(h->idx);
fail_ip:  cuvsCagraIndexParamsDestroy(h->ip);
fail_res:
  cuvsResourcesDestroy(h->res);
  pthread_mutex_destroy(&h->search_lock);
  free(h);
  fprintf(stderr, "[seekdb_cuvs] build failed: %s\n", cuvsGetLastErrorText());
  return NULL;
}

int seekdb_cuvs_search(void* handle, const float* query, long nq, long topk,
                       unsigned int* out_ids, float* out_dist)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (h == NULL || query == NULL || out_ids == NULL || nq <= 0 ||
      topk <= 0 || topk > h->n || h->dim <= 0) return 1;

  /* Validate products before converting to byte counts. */
  if ((size_t)nq > SIZE_MAX / (size_t)h->dim / sizeof(float) ||
      (size_t)nq > SIZE_MAX / (size_t)topk / sizeof(unsigned int) ||
      (size_t)nq > SIZE_MAX / (size_t)topk / sizeof(float)) return 2;
  const size_t query_bytes = (size_t)nq * (size_t)h->dim * sizeof(float);
  const size_t ids_bytes = (size_t)nq * (size_t)topk * sizeof(unsigned int);
  const size_t distances_bytes = (size_t)nq * (size_t)topk * sizeof(float);

  if (pthread_mutex_lock(&h->search_lock) != 0) return 3;
  int rc = 0;
  if (sk_reserve_gpu(h->res, (void**)&h->search_queries,
                     &h->queries_bytes, query_bytes)) { rc = 10; goto done; }
  if (sk_reserve_gpu(h->res, (void**)&h->search_ids,
                     &h->ids_bytes, ids_bytes)) { rc = 11; goto done; }
  if (sk_reserve_gpu(h->res, (void**)&h->search_distances,
                     &h->distances_bytes, distances_bytes)) { rc = 12; goto done; }
  if (cudaMemcpy(h->search_queries, query, query_bytes, cudaMemcpyDefault) != cudaSuccess) {
    rc = 13; goto done;
  }

  if (h->search_params == NULL) {
    if (cuvsCagraSearchParamsCreate(&h->search_params) != CUVS_SUCCESS) {
      rc = 14; goto done;
    }
    h->search_params->search_width = 4;
  }
  /* Keep the frozen V5 recall-sensitive search settings for both Top-10
   * and Top-100. A larger topk never decreases itopk_size. */
  {
    const size_t required_itopk = (size_t)topk * 4 > 512 ? (size_t)topk * 4 : 512;
    if (h->search_params->itopk_size < required_itopk)
      h->search_params->itopk_size = required_itopk;
  }

  {
    DLManagedTensor qt, nt, dt;
    long qs[2] = {nq, h->dim}, result_shape[2] = {nq, topk};
    qt.dl_tensor.data = h->search_queries;
    qt.dl_tensor.device.device_type = kDLCUDA;
    qt.dl_tensor.device.device_id = 0;
    qt.dl_tensor.ndim = 2;
    qt.dl_tensor.dtype.code = kDLFloat;
    qt.dl_tensor.dtype.bits = 32;
    qt.dl_tensor.dtype.lanes = 1;
    qt.dl_tensor.shape = qs;
    qt.dl_tensor.strides = 0;
    qt.dl_tensor.byte_offset = 0;
    nt = qt;
    nt.dl_tensor.data = h->search_ids;
    nt.dl_tensor.dtype.code = kDLUInt;
    nt.dl_tensor.shape = result_shape;
    dt = qt;
    dt.dl_tensor.data = h->search_distances;
    dt.dl_tensor.shape = result_shape;
    cuvsFilter f;
    f.type = NO_FILTER; f.addr = (uintptr_t)0;
    if (cuvsCagraSearch(h->res, h->search_params, h->idx, &qt, &nt, &dt, f)
        != CUVS_SUCCESS) { rc = 15; goto done; }
    if (cudaMemcpy(out_ids, h->search_ids, ids_bytes, cudaMemcpyDefault)
        != cudaSuccess) { rc = 16; goto done; }
    if (out_dist != NULL &&
        cudaMemcpy(out_dist, h->search_distances, distances_bytes, cudaMemcpyDefault)
        != cudaSuccess) { rc = 17; goto done; }
  }
done:
  pthread_mutex_unlock(&h->search_lock);
  if (rc) fprintf(stderr, "[seekdb_cuvs] search rc=%d: %s\n", rc, cuvsGetLastErrorText());
  return rc;
}

void seekdb_cuvs_free(void* handle)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (!h) return;
  sk_free_search(h);
  pthread_mutex_destroy(&h->search_lock);
  cuvsCagraIndexDestroy(h->idx);
  cuvsCagraIndexParamsDestroy(h->ip);
  cuvsResourcesDestroy(h->res);
  free(h);
}

int seekdb_cuvs_serialize(void* handle, const char* filename)
{
  sk_cuvs_index* index = (sk_cuvs_index*)handle;
  if (!index || !filename) return 1;
  if (cuvsCagraSerialize(index->res, filename, index->idx, true) != CUVS_SUCCESS) {
    fprintf(stderr, "[seekdb_cuvs] serialize failed: %s\n", cuvsGetLastErrorText());
    return 1;
  }
  return 0;
}

void* seekdb_cuvs_deserialize(const char* filename, long n, long dim)
{
  if (!filename || n <= 0 || dim <= 0) return NULL;
  sk_cuvs_index* index = (sk_cuvs_index*)calloc(1, sizeof(*index));
  if (!index) return NULL;
  if (pthread_mutex_init(&index->search_lock, NULL) != 0) { free(index); return NULL; }
  if (cuvsResourcesCreate(&index->res) != CUVS_SUCCESS) goto fail;
  if (cuvsCagraIndexParamsCreate(&index->ip) != CUVS_SUCCESS) goto fail_res;
  if (cuvsCagraIndexCreate(&index->idx) != CUVS_SUCCESS) goto fail_ip;
  if (cuvsCagraDeserialize(index->res, filename, index->idx) != CUVS_SUCCESS) goto fail_idx;
  {
    int64_t actual_n = 0;
    int64_t actual_dim = 0;
    if (cuvsCagraIndexGetSize(index->idx, &actual_n) != CUVS_SUCCESS ||
        cuvsCagraIndexGetDims(index->idx, &actual_dim) != CUVS_SUCCESS ||
        actual_n != n || actual_dim != dim) {
      fprintf(stderr, "[seekdb_cuvs] snapshot shape mismatch: %ld x %ld, expected %ld x %ld\n",
              (long)actual_n, (long)actual_dim, n, dim);
      goto fail_idx;
    }
  }
  index->n = n;
  index->dim = dim;
  return index;
fail_idx:
  cuvsCagraIndexDestroy(index->idx);
fail_ip:
  cuvsCagraIndexParamsDestroy(index->ip);
fail_res:
  cuvsResourcesDestroy(index->res);
fail:
  pthread_mutex_destroy(&index->search_lock);
  fprintf(stderr, "[seekdb_cuvs] deserialize failed: %s\n", cuvsGetLastErrorText());
  free(index);
  return NULL;
}

int seekdb_cuvs_cagra_knn(const float* base, long n, long dim,
                          const float* query, long nq, long topk,
                          unsigned int* out_ids)
{
  void* h = seekdb_cuvs_build(base, n, dim);
  if (!h) return 10;
  int rc = seekdb_cuvs_search(h, query, nq, topk, out_ids, NULL);
  seekdb_cuvs_free(h);
  return rc;
}
