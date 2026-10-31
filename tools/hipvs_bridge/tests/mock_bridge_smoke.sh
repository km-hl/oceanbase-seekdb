#!/usr/bin/env bash
# CPU-only mock of the hipVS ABI; validates C syntax + scratch reuse, not GPU recall.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/cuvs/core" "$TMP/cuvs/neighbors" "$TMP/dlpack"
cat > "$TMP/dlpack/dlpack.h" <<'H'
#ifndef MOCK_DLPACK_H
#define MOCK_DLPACK_H
#include <stdint.h>
enum { kDLCPU=1, kDLCUDA=2, kDLFloat=2, kDLUInt=1 };
typedef struct { int device_type, device_id; } DLDevice;
typedef struct { uint8_t code,bits; uint16_t lanes; } DLDataType;
typedef struct { void *data; DLDevice device; int ndim; DLDataType dtype; int64_t *shape,*strides; uint64_t byte_offset; } DLTensor;
typedef struct { DLTensor dl_tensor; } DLManagedTensor;
#endif
H
cat > "$TMP/cuvs/core/c_api.h" <<'H'
#ifndef MOCK_CUVS_CORE_H
#define MOCK_CUVS_CORE_H
#include <stddef.h>
#define CUVS_SUCCESS 0
typedef struct MockResource* cuvsResources_t;
int cuvsResourcesCreate(cuvsResources_t*);
int cuvsResourcesDestroy(cuvsResources_t);
int cuvsRMMAlloc(cuvsResources_t,void**,size_t);
int cuvsRMMFree(cuvsResources_t,void*,size_t);
const char* cuvsGetLastErrorText(void);
#endif
H
cat > "$TMP/cuvs/neighbors/cagra.h" <<'H'
#ifndef MOCK_CUVS_CAGRA_H
#define MOCK_CUVS_CAGRA_H
#include "dlpack/dlpack.h"
#include "cuvs/core/c_api.h"
#include <stdint.h>
enum { NN_DESCENT=1, NO_FILTER=0 };
typedef struct MockIp { int build_algo; size_t graph_degree,intermediate_graph_degree,nn_descent_niter; } *cuvsCagraIndexParams_t;
typedef struct MockIdx { long n,dim; } *cuvsCagraIndex_t;
typedef struct MockSp { size_t itopk_size; int search_width; } *cuvsCagraSearchParams_t;
typedef struct { int type; uintptr_t addr; } cuvsFilter;
int cuvsCagraIndexParamsCreate(cuvsCagraIndexParams_t*);
int cuvsCagraIndexParamsDestroy(cuvsCagraIndexParams_t);
int cuvsCagraIndexCreate(cuvsCagraIndex_t*);
int cuvsCagraIndexDestroy(cuvsCagraIndex_t);
int cuvsCagraBuild(cuvsResources_t,cuvsCagraIndexParams_t,DLManagedTensor*,cuvsCagraIndex_t);
int cuvsCagraSearchParamsCreate(cuvsCagraSearchParams_t*);
int cuvsCagraSearchParamsDestroy(cuvsCagraSearchParams_t);
int cuvsCagraSearch(cuvsResources_t,cuvsCagraSearchParams_t,cuvsCagraIndex_t,DLManagedTensor*,DLManagedTensor*,DLManagedTensor*,cuvsFilter);
int cuvsCagraSerialize(cuvsResources_t,const char*,cuvsCagraIndex_t,int);
int cuvsCagraDeserialize(cuvsResources_t,const char*,cuvsCagraIndex_t);
int cuvsCagraIndexGetSize(cuvsCagraIndex_t,int64_t*);
int cuvsCagraIndexGetDims(cuvsCagraIndex_t,int64_t*);
#endif
H
cat > "$TMP/cuvs/cuda_runtime.h" <<'H'
#include <string.h>
#define cudaSuccess 0
#define cudaMemcpyDefault 4
static inline int cudaMemcpy(void*d,const void*s,size_t n,int k){(void)k;memcpy(d,s,n);return 0;}
H
cat > "$TMP/mock.c" <<'C'
#include "seekdb_cuvs_bridge.h"
#include "cuvs/neighbors/cagra.h"
#include <stdio.h>
#include <stdlib.h>
struct MockResource { int dummy; };
static int allocations=0, frees=0, sp_created=0;
int cuvsResourcesCreate(cuvsResources_t*r){*r=calloc(1,sizeof(**r));return *r?0:1;}
int cuvsResourcesDestroy(cuvsResources_t r){free(r);return 0;}
int cuvsRMMAlloc(cuvsResources_t r,void**p,size_t n){(void)r;allocations++;*p=malloc(n);return *p?0:1;}
int cuvsRMMFree(cuvsResources_t r,void*p,size_t n){(void)r;(void)n;frees++;free(p);return 0;}
const char*cuvsGetLastErrorText(void){return "mock";}
int cuvsCagraIndexParamsCreate(cuvsCagraIndexParams_t*p){*p=calloc(1,sizeof(**p));return *p?0:1;}
int cuvsCagraIndexParamsDestroy(cuvsCagraIndexParams_t p){free(p);return 0;}
int cuvsCagraIndexCreate(cuvsCagraIndex_t*p){*p=calloc(1,sizeof(**p));return *p?0:1;}
int cuvsCagraIndexDestroy(cuvsCagraIndex_t p){free(p);return 0;}
int cuvsCagraBuild(cuvsResources_t r,cuvsCagraIndexParams_t p,DLManagedTensor*t,cuvsCagraIndex_t idx){
 (void)r;if(p->build_algo!=NN_DESCENT||p->graph_degree!=128||p->intermediate_graph_degree!=256||p->nn_descent_niter!=80)return 1;
 idx->n=t->dl_tensor.shape[0];idx->dim=t->dl_tensor.shape[1];return 0;
}
int cuvsCagraSearchParamsCreate(cuvsCagraSearchParams_t*p){sp_created++;*p=calloc(1,sizeof(**p));return *p?0:1;}
int cuvsCagraSearchParamsDestroy(cuvsCagraSearchParams_t p){free(p);return 0;}
int cuvsCagraSearch(cuvsResources_t r,cuvsCagraSearchParams_t p,cuvsCagraIndex_t idx,DLManagedTensor*q,DLManagedTensor*n,DLManagedTensor*d,cuvsFilter f){
 (void)r;(void)idx;(void)q;if(f.type!=NO_FILTER||p->itopk_size<512||p->search_width!=4)return 1;
 long count=n->dl_tensor.shape[0]*n->dl_tensor.shape[1];
 for(long i=0;i<count;i++){((unsigned*)n->dl_tensor.data)[i]=(unsigned)i;((float*)d->dl_tensor.data)[i]=(float)i;}
 return 0;
}
int cuvsCagraSerialize(cuvsResources_t r,const char*file,cuvsCagraIndex_t idx,int copy){
 (void)r;(void)idx;(void)copy;FILE*f=fopen(file,"wb");if(!f)return 1;fputs("mock",f);fclose(f);return 0;
}
int cuvsCagraDeserialize(cuvsResources_t r,const char*file,cuvsCagraIndex_t idx){
 (void)r;FILE*f=fopen(file,"rb");if(!f)return 1;fclose(f);idx->n=256;idx->dim=8;return 0;
}
int cuvsCagraIndexGetSize(cuvsCagraIndex_t idx,int64_t*n){*n=idx->n;return 0;}
int cuvsCagraIndexGetDims(cuvsCagraIndex_t idx,int64_t*d){*d=idx->dim;return 0;}
static void test(int ok,const char*msg){if(!ok){fprintf(stderr,"FAIL %s\n",msg);exit(1);}}
int main(void){
 float base[256*8]={0},query[8]={0},distance[100]={0};unsigned ids[100]={0};
 void*h=seekdb_cuvs_build(base,256,8);test(h!=NULL,"build");
 test(seekdb_cuvs_search(h,query,1,10,ids,distance)==0,"top10");
 test(allocations==3&&sp_created==1,"first alloc");
 test(seekdb_cuvs_search(h,query,1,10,ids,distance)==0,"repeat top10");
 test(allocations==3&&sp_created==1&&ids[9]==9&&distance[9]==9.0f,"reuse + results");
 test(seekdb_cuvs_search(h,query,1,100,ids,distance)==0,"top100");
 test(allocations==5&&sp_created==1,"resize output only");
 test(seekdb_cuvs_serialize(h,"/tmp/amd-cuvs-mock.bin")==0,"serialize");
 seekdb_cuvs_free(h);test(frees==allocations,"cleanup");
 h=seekdb_cuvs_deserialize("/tmp/amd-cuvs-mock.bin",256,8);test(h!=NULL,"deserialize");
 test(seekdb_cuvs_search(h,query,1,10,ids,distance)==0,"reload query");
 seekdb_cuvs_free(h);test(frees==allocations,"reload cleanup");
 remove("/tmp/amd-cuvs-mock.bin");
 puts("PASS mock hipVS bridge, search scratch reuse, Top-10/100 and snapshot");
 return 0;
}
C
cc -std=c11 -Wall -Wextra -Werror -D__HIP_PLATFORM_AMD__ -I"$TMP" \
   -I"$ROOT/tools/hipvs_bridge" "$ROOT/tools/hipvs_bridge/seekdb_cuvs_bridge.c" \
   "$TMP/mock.c" -pthread -o "$TMP/bridge-test"
"$TMP/bridge-test"
