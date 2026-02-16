# Content Bank 
Content based storage system for Tiny Library

## Summary
* ContentBank is a content storage system for Tiny Library. 
* Content is stored with metadata and binary data in separate layers, with the metadata replaicated and the binary data chunked and replicated.
* 


## Database
The deployment environment is across a set of nodes connected by internet protocols. The nodes are typically low power single board computers like raspberry pi or small cloud instances like digital ocean, for example 2-4 CPUs with 8GB memory. The network connectivity will range from data center and LAN to consumer internet. The system should be resilient and tolerate the loss or temporary loss of nodes. There should be a range of replication factor available to tune the data integrity on a granular basis, and to tune the data integrity of metadata vs, binary data. The system will allow multiple users and should provide typical data isolation between user accounts.